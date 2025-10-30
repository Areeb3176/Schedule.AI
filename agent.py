import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
import google.generativeai as genai
from requests_oauthlib import OAuth2Session
import pytz

# Import database functions
from database import get_all_users, get_user_tokens, is_token_expired, User

# Import from utils.py instead of app.py
from utils import refresh_access_token, get_valid_token, GOOGLE_CLIENT_ID

load_dotenv()

# ============================================
# 📧 EMAIL CONFIGURATION
# ============================================

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# ============================================
# 🤖 GEMINI AI CONFIGURATION
# ============================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Model select karo (gemini-pro is free and fast)
model = genai.GenerativeModel('gemini-pro')

# ============================================
# 🌍 TIMEZONE CONFIGURATION (from .env)
# ============================================

USER_TIMEZONE = os.getenv("USER_TIMEZONE", "UTC")  # Default UTC
FETCH_DAYS_AHEAD = int(os.getenv("FETCH_DAYS_AHEAD", "7"))  # Default 7 days


# ============================================
# 🕐 TIME FORMATTING HELPER
# ============================================

def format_time_12hr(time_str):
    """
    Convert ISO time to readable 12-hour format (keeping original timezone)
    Example: 2025-10-28T14:30:00+05:00 -> 2:30 PM
    """
    try:
        # Parse ISO format (handles both Z and +05:00 formats)
        if 'T' in time_str:
            # DateTime format
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            # Return time in 12-hour format
            return dt.strftime('%I:%M %p').lstrip('0')
        else:
            # All-day event (date only)
            return "All Day"
    except:
        return time_str


def format_date_friendly(time_str):
    """
    Convert ISO date to friendly format
    Example: 2025-10-28 -> Monday, October 28, 2025
    """
    try:
        if 'T' in time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(time_str)
        return dt.strftime('%A, %B %d, %Y')
    except:
        return time_str


def format_datetime_full(time_str):
    """
    Full datetime with day and date
    Example: Monday, Oct 28 at 2:30 PM
    """
    try:
        if 'T' in time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime('%A, %b %d at %I:%M %p').replace(' 0', ' ')
        else:
            dt = datetime.fromisoformat(time_str)
            return dt.strftime('%A, %b %d (All Day)')
    except:
        return time_str


# ============================================
# 📅 STEP 1: FETCH CALENDAR EVENTS
# ============================================

def fetch_user_calendar_events(user_id, user_email):
    """
    Ek user ke calendar events fetch karo
    
    Args:
        user_id: Database user ID
        user_email: User ka email (logging ke liye)
    
    Returns:
        List of events or None if error
    """
    print(f"\n{'='*60}")
    print(f"📅 Fetching calendar for: {user_email}")
    print(f"{'='*60}")
    
    try:
        # Step 1: Valid token lo (auto-refresh if expired)
        token_data = get_valid_token(user_id)
        
        if not token_data:
            print(f"❌ No valid token for user: {user_email}")
            return None
        
        print(f"✅ Valid token obtained")
        
        # Step 2: OAuth2Session create karo
        token = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data['refresh_token'],
            'token_type': 'Bearer'
        }
        
        google = OAuth2Session(GOOGLE_CLIENT_ID, token=token)
        
        # Step 3: Calendar API call - User timezone ke hisaab se
        user_tz = pytz.timezone(USER_TIMEZONE)
        now_user = datetime.now(user_tz)
        
        # Aaj ki subah se shuru karo (00:00)
        start_of_day = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Aglay N din tak fetch karo
        end_time = start_of_day + timedelta(days=FETCH_DAYS_AHEAD)
        
        # UTC mein convert karo (Google API ke liye) - with Z suffix
        time_min = start_of_day.astimezone(pytz.UTC).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        time_max = end_time.astimezone(pytz.UTC).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        
        print(f"🌍 Timezone: {USER_TIMEZONE}")
        print(f"📅 Fetching from: {start_of_day.strftime('%Y-%m-%d %H:%M')} ({USER_TIMEZONE})")
        print(f"📅 Fetching to: {end_time.strftime('%Y-%m-%d %H:%M')} ({USER_TIMEZONE})")
        print(f"🔍 API Request: {time_min} to {time_max}")
        
        response = google.get(
            'https://www.googleapis.com/calendar/v3/calendars/primary/events?'
            f'maxResults=50&orderBy=startTime&singleEvents=true&'
            f'timeMin={time_min}&timeMax={time_max}'
        )
        
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            print(f"Response: {response.text}")
            return None
        
        events = response.json().get('items', [])
        print(f"✅ Found {len(events)} events")
        
        return events
        
    except Exception as e:
        print(f"❌ Exception while fetching calendar: {str(e)}")
        return None


# ============================================
# 🤖 STEP 2: GENERATE AI SUMMARY (GEMINI)
# ============================================

def generate_ai_summary(events, user_name):
    """
    Gemini AI se calendar events ka summary generate karo (professional email style)
    
    Args:
        events: List of calendar events
        user_name: User ka naam (personalization ke liye)
    
    Returns:
        AI-generated summary string
    """
    print(f"\n{'='*60}")
    print(f"🤖 Generating AI summary with Gemini")
    print(f"{'='*60}")
    
    if not events:
        return create_professional_email(user_name, [], is_empty=True)
    
    try:
        # Events ko readable format mein convert karo (with DATE and TIME)
        events_text = ""
        for i, event in enumerate(events, 1):
            start = event['start'].get('dateTime', event['start'].get('date'))
            formatted_time = format_time_12hr(start)
            formatted_date = format_date_friendly(start)  # DATE ADDED
            summary = event.get('summary', 'Untitled Event')
            description = event.get('description', 'No description')
            location = event.get('location', 'No location')
            
            events_text += f"""
Event {i}:
- Title: {summary}
- Date: {formatted_date}
- Time: {formatted_time}
- Location: {location}
- Description: {description}

"""
        
        # Gemini ko prompt bhejo
        prompt = f"""
You are a professional executive assistant. Create a concise, well-formatted daily calendar summary email.

User Name: {user_name}
Number of Events: {len(events)}

Events:
{events_text}

Create a professional HTML email that:
1. Uses a clean, corporate design
2. Starts with a brief, professional greeting
3. Provides a quick overview
4. Lists each event clearly with DATE, TIME (12-hour format), title, and location
5. Adds brief, helpful notes if relevant
6. Ends with a professional closing

IMPORTANT REQUIREMENTS:
- ALWAYS show the full DATE for each event (e.g., "Monday, Oct 28" or "Tuesday, Oct 29")
- Group events by date if they span multiple days
- Use clear date headers like "Today - Monday, Oct 28" and "Tomorrow - Tuesday, Oct 29"
- Keep it scannable and easy to read
- Maximum 300 words

Return ONLY the email body HTML (no <html>, <head>, or <body> tags).
"""
        
        print(f"📤 Sending prompt to Gemini...")
        print(f"Events count: {len(events)}")
        
        # Gemini API call
        response = model.generate_content(prompt)
        
        if not response or not response.text:
            print(f"⚠️ Empty response from Gemini, using fallback")
            return create_professional_email(user_name, events)
        
        summary = response.text
        
        # Wrap AI content in professional email template
        final_email = create_professional_email(user_name, events, ai_content=summary)
        
        print(f"✅ AI summary generated ({len(final_email)} characters)")
        
        return final_email
        
    except Exception as e:
        print(f"❌ Gemini API error: {str(e)}")
        print(f"⚠️ Using fallback summary")
        return create_professional_email(user_name, events)


def create_professional_email(user_name, events, ai_content=None, is_empty=False):
    """
    Professional email template with modern design
    """
    current_date = datetime.now(pytz.UTC).strftime('%A, %B %d, %Y')
    
    if is_empty:
        content = f"""
        <div style="text-align: center; padding: 40px 20px;">
            <div style="font-size: 48px; margin-bottom: 20px;">🔭</div>
            <h2 style="color: #1f2937; margin-bottom: 10px;">No Events Scheduled</h2>
            <p style="color: #6b7280; font-size: 16px;">You have a free day ahead. Enjoy your time!</p>
        </div>
        """
    elif ai_content:
        content = ai_content
    else:
        # Fallback content - with DATE and TIME
        content = f"""
        <h2 style="color: #1f2937; margin-bottom: 10px;">Good Morning, {user_name}!</h2>
        <p style="color: #4b5563; font-size: 16px; margin-bottom: 30px;">
            You have <strong>{len(events)} event(s)</strong> scheduled.
        </p>
        
        <div style="background: #f9fafb; padding: 20px; border-radius: 8px; border-left: 4px solid #3b82f6;">
        """
        
        for i, event in enumerate(events, 1):
            start = event['start'].get('dateTime', event['start'].get('date'))
            formatted_full_datetime = format_datetime_full(start)  # FULL DATE + TIME
            summary = event.get('summary', 'Untitled Event')
            location = event.get('location', '')
            
            content += f"""
            <div style="margin-bottom: 20px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
                <div style="margin-bottom: 8px;">
                    <span style="background: #3b82f6; color: white; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 600; display: inline-block; margin-bottom: 8px;">
                        📅 {formatted_full_datetime}
                    </span>
                </div>
                <div style="margin-left: 4px;">
                    <span style="color: #1f2937; font-size: 16px; font-weight: 600;">
                        {summary}
                    </span>
                    {f'<div style="color: #6b7280; font-size: 14px; margin-top: 5px;">📍 {location}</div>' if location else ''}
                </div>
            </div>
            """
        
        content += "</div>"
    
    # Full email template
    email_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f3f4f6; padding: 40px 0;">
            <tr>
                <td align="center">
                    <!-- Main Container -->
                    <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); overflow: hidden;">
                        
                        <!-- Header -->
                        <tr>
                            <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 700;">
                                    📅 Daily Calendar Summary
                                </h1>
                                <p style="color: #e0e7ff; margin: 10px 0 0 0; font-size: 14px;">
                                    {current_date}
                                </p>
                            </td>
                        </tr>
                        
                        <!-- Content -->
                        <tr>
                            <td style="padding: 40px 30px;">
                                {content}
                            </td>
                        </tr>
                        
                        <!-- Footer -->
                        <tr>
                            <td style="background-color: #f9fafb; padding: 30px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="color: #6b7280; font-size: 14px; margin: 0 0 10px 0;">
                                    Have a productive day! 💪
                                </p>
                                <p style="color: #9ca3af; font-size: 12px; margin: 0;">
                                    This is an automated email from your Smart Calendar Assistant<br>
                                    Powered by AI • Delivered daily at midnight UTC
                                </p>
                            </td>
                        </tr>
                        
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    return email_html


# ============================================
# 📧 STEP 3: SEND EMAIL
# ============================================

def send_email(to_email, subject, html_content):
    """
    User ko email bhejo
    
    Args:
        to_email: Recipient email
        subject: Email subject
        html_content: HTML email body
    
    Returns:
        True if successful, False otherwise
    """
    print(f"\n{'='*60}")
    print(f"📧 Sending email to: {to_email}")
    print(f"{'='*60}")
    
    if not EMAIL_USER or not EMAIL_PASSWORD:
        print("❌ Email credentials missing in .env file!")
        return False
    
    try:
        # Email message create karo
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Calendar Assistant <{EMAIL_USER}>"
        msg['To'] = to_email
        
        # HTML content add karo
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        # SMTP connection
        print(f"🔌 Connecting to {EMAIL_HOST}:{EMAIL_PORT}")
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        
        print(f"🔑 Logging in as {EMAIL_USER}")
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        
        print(f"📤 Sending email...")
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email sent successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Email send failed: {str(e)}")
        return False


# ============================================
# 🚀 MAIN AGENT FUNCTIONS
# ============================================

def send_email_to_users(user_ids=None, broadcast_from_user_id=None, include_admins=True):
    """
    Users ko email bhejo with role-based filtering
    
    Args:
        user_ids: List of user IDs to send emails to. If None, send to all users.
        broadcast_from_user_id: If provided, use THIS user's calendar for ALL emails (broadcast mode)
        include_admins: If False, skip admin users (only send to regular users)
    
    Returns:
        Dictionary with success/failed counts
    """
    print("\n" + "="*60)
    if broadcast_from_user_id:
        print("📢 BROADCAST MODE - Sending one user's events to all")
    else:
        print("🤖 PERSONALIZED MODE - Each user gets their own events")
    print("="*60)
    print(f"⏰ Time: {datetime.now(pytz.UTC)}")
    print(f"🌍 Timezone: {USER_TIMEZONE}")
    print(f"📅 Fetching {FETCH_DAYS_AHEAD} days ahead")
    print(f"👥 Include Admins: {include_admins}")
    print("="*60 + "\n")
    
    # Get recipient users with role filtering
    if user_ids:
        users = User.query.filter(User.id.in_(user_ids)).all()
        print(f"👥 Sending to {len(users)} selected user(s)")
    else:
        users = get_all_users()
        print(f"👥 Total users in database: {len(users)}")
        
        # Filter by role if needed
        if not include_admins:
            users = [u for u in users if not u.is_admin()]
            print(f"👤 Filtered to {len(users)} regular users (admins excluded)")
    
    if not users:
        print("⚠️ No users found")
        return {'total': 0, 'success': 0, 'failed': 0}
    
    # Broadcast mode: Fetch events ONCE from broadcast user
    broadcast_events = None
    broadcast_user_name = None
    if broadcast_from_user_id:
        broadcast_user = User.query.get(broadcast_from_user_id)
        if broadcast_user:
            print(f"\n📢 Fetching events from: {broadcast_user.name} ({broadcast_user.email}) - {broadcast_user.role.upper()}")
            broadcast_events = fetch_user_calendar_events(broadcast_from_user_id, broadcast_user.email)
            broadcast_user_name = broadcast_user.name
            
            if broadcast_events is None:
                print(f"❌ Failed to fetch broadcast events")
                return {'total': len(users), 'success': 0, 'failed': len(users)}
            
            print(f"✅ Will broadcast {len(broadcast_events)} events to all users\n")
    
    # Results tracking
    results = {
        'total': len(users),
        'success': 0,
        'failed': 0
    }
    
    # Process each user
    for user in users:
        print(f"\n{'='*60}")
        print(f"👤 Sending to: {user.name} ({user.email}) - {user.role.upper()}")
        print(f"{'='*60}")
        
        try:
            # Decide which events to use
            if broadcast_from_user_id and broadcast_events is not None:
                # Broadcast mode: Use broadcast user's events
                events = broadcast_events
                summary_name = f"{broadcast_user_name}'s Schedule"
                print(f"📢 Using broadcast events from {broadcast_user_name}")
            else:
                # Personal mode: Fetch each user's own events
                events = fetch_user_calendar_events(user.id, user.email)
                summary_name = user.name
                
                if events is None:
                    print(f"❌ Failed to fetch events for {user.email}")
                    results['failed'] += 1
                    continue
            
            # Generate AI summary
            summary_html = generate_ai_summary(events, summary_name)
            
            # Send email
            if broadcast_from_user_id:
                subject = f"📅 Team Calendar Update - {datetime.now(pytz.UTC).strftime('%B %d, %Y')}"
            else:
                subject = f"📅 Your Daily Calendar Summary - {datetime.now(pytz.UTC).strftime('%B %d, %Y')}"
            
            email_sent = send_email(
                to_email=user.email,
                subject=subject,
                html_content=summary_html
            )
            
            if email_sent:
                print(f"✅ Successfully sent to {user.email}")
                results['success'] += 1
            else:
                print(f"❌ Email failed for {user.email}")
                results['failed'] += 1
                
        except Exception as e:
            print(f"❌ Error processing {user.email}: {str(e)}")
            results['failed'] += 1
    
    # Print summary
    print("\n" + "="*60)
    print("📊 EXECUTION SUMMARY")
    print("="*60)
    print(f"Total Recipients: {results['total']}")
    print(f"✅ Success: {results['success']}")
    print(f"❌ Failed: {results['failed']}")
    print("="*60 + "\n")
    
    return results


def run_daily_summary_agent(broadcast_mode=False, send_to_admins=False):
    """
    🎯 MAIN FUNCTION - Daily summary agent with role-based control
    
    Args:
        broadcast_mode: If True, use first admin's calendar for all emails
                       If False, each user gets their own calendar events (default)
        send_to_admins: If True, include admins in recipients
                       If False, only send to regular users (default)
    """
    if broadcast_mode:
        # Get first admin as broadcaster
        admin_user = User.query.filter_by(role='admin').first()
        if admin_user:
            return send_email_to_users(
                user_ids=None, 
                broadcast_from_user_id=admin_user.id,
                include_admins=send_to_admins
            )
        else:
            print("❌ No admin found for broadcast")
            return {'total': 0, 'success': 0, 'failed': 0}
    else:
        # Normal mode: everyone gets their own events
        return send_email_to_users(
            user_ids=None, 
            broadcast_from_user_id=None,
            include_admins=send_to_admins
        )


# ============================================
# 🧪 TESTING FUNCTIONS - REAL CALENDAR DATA
# ============================================

def test_email_with_real_calendar():
    
    print("\n" + "="*60)
    print("🧪 TESTING EMAIL WITH REAL CALENDAR DATA")
    print("="*60 + "\n")
    
    # Get first user from database 
    from database import User
    user = User.query.first()
    
    if not user:
        print("❌ No user found in database. Please login first.")
        return False
    
    print(f"👤 Testing with user: {user.name} ({user.email}) - {user.role.upper()}")
    
    # Fetch REAL calendar events
    events = fetch_user_calendar_events(user.id, user.email)
    
    if events is None:
        print("❌ Failed to fetch calendar events")
        return False
    
    print(f"✅ Found {len(events)} real event(s)")
    
    # Generate AI summary from REAL events
    summary_html = generate_ai_summary(events, user.name)
    
    # Send test email to yourself
    test_email_addr = EMAIL_USER  # Apne aap ko bhejega
    
    if not test_email_addr:
        print("❌ Please set EMAIL_USER in .env file")
        return False
    
    subject = "🧪 TEST - Your Real Calendar Summary"
    
    success = send_email(test_email_addr, subject, summary_html)
    
    if success:
        print("\n✅ Test email sent with REAL calendar data!")
        print(f"📧 Check inbox: {test_email_addr}")
    
    return success


# ============================================
# 🎯 MANUAL EXECUTION (for testing)
# ============================================

if __name__ == "__main__":
    # ✅ RECOMMENDED: Test with real calendar data
    print("\n🚀 Testing with REAL calendar data...")
    test_email_with_real_calendar()
    
    # Option: Run full agent (will process all real users)
    # run_daily_summary_agent(broadcast_mode=False, send_to_admins=False)