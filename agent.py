import os
import requests
import base64
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
import google.generativeai as genai
from requests_oauthlib import OAuth2Session
import pytz
from database import (
    get_all_users, get_user_tokens, is_token_expired, User,
    log_email_sent  
)
from utils import refresh_access_token, get_valid_token, GOOGLE_CLIENT_ID

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
model = None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model_names = ['gemini-pro'] 
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                test_response = model.generate_content("Hello")
                if test_response:
                    print(f"[+] Using Gemini model: {model_name}")
                    break
            except Exception as e:
                print(f"[!] {model_name} not available: {str(e)}")
                continue
        if not model:
            print("[!] No Gemini models available, will use fallback")
            
    except Exception as e:
        print(f"[!] Gemini setup failed: {str(e)}")
        model = None
else:
    print("[!] No GEMINI_API_KEY found in .env")

USER_TIMEZONE = os.getenv("USER_TIMEZONE", "UTC")

def format_time_12hr(time_str):
    try:
        if 'T' in time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime('%I:%M %p').lstrip('0')
        else:
            return "All Day"
    except:
        return time_str

def format_date_friendly(time_str):
    try:
        if 'T' in time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(time_str)
        return dt.strftime('%A, %B %d, %Y')
    except:
        return time_str


def format_datetime_full(time_str):
    try:
        if 'T' in time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime('%A, %b %d at %I:%M %p').replace(' 0', ' ')
        else:
            dt = datetime.fromisoformat(time_str)
            return dt.strftime('%A, %b %d (All Day)')
    except:
        return time_str

def fetch_user_calendar_events(user_id, user_email, fetch_days_ahead=7):
    """User ke calendar events fetch karo"""
    print(f"\n{'='*60}")
    print(f"📅 Fetching calendar for: {user_email}")
    print(f"{'='*60}")
    
    try:
        token_data = get_valid_token(user_id)
        
        if not token_data:
            print(f"❌ No valid token for user: {user_email}")
            return None
        
        print(f"✅ Valid token obtained")
        
        token = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data['refresh_token'],
            'token_type': 'Bearer'
        }
        
        google = OAuth2Session(GOOGLE_CLIENT_ID, token=token)
        
        user_tz = pytz.timezone(USER_TIMEZONE)
        now_user = datetime.now(user_tz)
        start_of_day = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_of_day + timedelta(days=fetch_days_ahead)
        
        time_min = start_of_day.astimezone(pytz.UTC).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        time_max = end_time.astimezone(pytz.UTC).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        
        print(f"🌍 Timezone: {USER_TIMEZONE}")
        print(f"📅 Fetching from: {start_of_day.strftime('%Y-%m-%d %H:%M')}")
        print(f"📅 Fetching to: {end_time.strftime('%Y-%m-%d %H:%M')}")
        
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
    
def generate_ai_summary(events, user_name, fetch_days_ahead=7):
    """Gemini AI se summary generate karo"""
    print(f"\n{'='*60}")
    print(f"🤖 Generating AI summary")
    print(f"{'='*60}")
    
    if not events:
        print("[!] No events found, creating empty email")
        return create_professional_email(user_name, [], fetch_days_ahead=fetch_days_ahead, is_empty=True)
    
    if not model:
        print("[!] Gemini not available, using fallback template")
        return create_professional_email(user_name, events, fetch_days_ahead=fetch_days_ahead)
    
    try:
        events_text = ""
        for i, event in enumerate(events, 1):
            start = event['start'].get('dateTime', event['start'].get('date'))
            formatted_time = format_time_12hr(start)
            formatted_date = format_date_friendly(start)
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
        
        prompt = f"""
You are a professional executive assistant. Create a concise, well-formatted calendar summary email for the next {fetch_days_ahead} days.

User Name: {user_name}
Number of Events: {len(events)}
Time Period: Next {fetch_days_ahead} days

Events:
{events_text}

Create a professional HTML email that:
1. Uses a clean, corporate design
2. Starts with a brief, professional greeting
3. Mentions the time period ({fetch_days_ahead} days)
4. Provides a quick overview
5. Lists each event clearly with DATE, TIME (12-hour format), title, and location
6. Groups events by date if they span multiple days
7. Adds brief, helpful notes if relevant
8. Ends with a professional closing

IMPORTANT REQUIREMENTS:
- ALWAYS show the full DATE for each event
- Use clear date headers
- Keep it scannable and easy to read
- Maximum 300 words

Return ONLY the email body HTML (no <html>, <head>, or <body> tags).
"""
        
        print(f"📤 Sending prompt to Gemini...")
        
        response = model.generate_content(prompt)
        
        if not response or not response.text:
            print(f"⚠️ Empty response from Gemini, using fallback")
            return create_professional_email(user_name, events, fetch_days_ahead=fetch_days_ahead)
        
        summary = response.text
        final_email = create_professional_email(user_name, events, fetch_days_ahead=fetch_days_ahead, ai_content=summary)
        
        print(f"✅ AI summary generated successfully")
        
        return final_email
        
    except Exception as e:
        print(f"❌ Gemini API error: {str(e)}")
        print(f"⚠️ Using fallback summary")
        return create_professional_email(user_name, events, fetch_days_ahead=fetch_days_ahead)


def create_professional_email(user_name, events, fetch_days_ahead=7, ai_content=None, is_empty=False):
    """Professional email template"""
    current_date = datetime.now(pytz.UTC).strftime('%A, %B %d, %Y')
    
    if fetch_days_ahead == 1:
        period_text = "Today"
    elif fetch_days_ahead == 7:
        period_text = "This Week"
    else:
        period_text = f"Next {fetch_days_ahead} Days"
    
    if is_empty:
        content = f"""
        <div style="text-align: center; padding: 40px 20px;">
            <div style="font-size: 48px; margin-bottom: 20px;">🔭</div>
            <h2 style="color: #1f2937; margin-bottom: 10px;">No Events Scheduled</h2>
            <p style="color: #6b7280; font-size: 16px;">You have no events in the next {fetch_days_ahead} days. Enjoy your time!</p>
        </div>
        """
    elif ai_content:
        content = ai_content
    else:
        content = f"""
        <h2 style="color: #1f2937; margin-bottom: 10px;">Good Morning, {user_name}!</h2>
        <p style="color: #4b5563; font-size: 16px; margin-bottom: 30px;">
            You have <strong>{len(events)} event(s)</strong> scheduled for the next {fetch_days_ahead} days.
        </p>
        
        <div style="background: #f9fafb; padding: 20px; border-radius: 8px; border-left: 4px solid #3b82f6;">
        """
        
        for i, event in enumerate(events, 1):
            start = event['start'].get('dateTime', event['start'].get('date'))
            formatted_full_datetime = format_datetime_full(start)
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
                    <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); overflow: hidden;">
                        <tr>
                            <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 700;">
                                    📅 {period_text} Calendar Summary
                                </h1>
                                <p style="color: #e0e7ff; margin: 10px 0 0 0; font-size: 14px;">
                                    {current_date}
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 40px 30px;">
                                {content}
                            </td>
                        </tr>
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

def send_email(to_email, subject, html_content, user_id, user_name, events_count, fetch_days):
    print(f"🚀 Preparing to send email to {to_email} via Gmail API...")
    
    # 1. Valid token lo
    token_data = get_valid_token(user_id)
    
    if not token_data or not token_data.get('access_token'):
        print(f"❌ Failed to get valid token for user_id: {user_id}")
        log_email_sent(
            user_id=user_id,
            user_name=user_name,
            user_email=to_email,
            subject=subject,
            events_count=events_count,
            fetch_days=fetch_days,
            status='failed',
            error_message="No valid OAuth token"
        )
        return False
        
    access_token = token_data['access_token']
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['To'] = to_email
        msg['From'] = 'me'  
        
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        body = {'raw': raw_message}
        
        print(f"📤 Sending request to Gmail API...")
        
        response = requests.post(
            'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
            headers=headers,
            json=body,
            timeout=30
        )
        
        print(f"📥 Gmail API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            print(f"✅ Email sent successfully to {to_email}")
            log_email_sent(
                user_id=user_id,
                user_name=user_name,
                user_email=to_email,
                subject=subject,
                events_count=events_count,
                fetch_days=fetch_days,
                status='success'
            )
            return True
            
        elif response.status_code == 403:
            # ❌ SCOPE ERROR - Most common issue
            error_msg = "Insufficient authentication scopes. User needs to re-authenticate with Gmail send permission."
            print(f"❌ SCOPE ERROR: {error_msg}")
            print(f"⚠️ SOLUTION: User must logout and login again to grant Gmail.send scope")
            
            log_email_sent(
                user_id=user_id,
                user_name=user_name,
                user_email=to_email,
                subject=subject,
                events_count=events_count,
                fetch_days=fetch_days,
                status='failed',
                error_message=error_msg
            )
            return False
            
        else:
            # Other errors
            try:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
            except:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            
            print(f"❌ Gmail API Error: {error_msg}")
            
            log_email_sent(
                user_id=user_id,
                user_name=user_name,
                user_email=to_email,
                subject=subject,
                events_count=events_count,
                fetch_days=fetch_days,
                status='failed',
                error_message=error_msg
            )
            return False

    except requests.exceptions.Timeout:
        error_msg = "Gmail API request timeout (30s)"
        print(f"❌ {error_msg}")
        log_email_sent(
            user_id=user_id, user_name=user_name, user_email=to_email,
            subject=subject, events_count=events_count, fetch_days=fetch_days,
            status='failed', error_message=error_msg
        )
        return False
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Request failed: {str(e)}"
        print(f"❌ {error_msg}")
        log_email_sent(
            user_id=user_id, user_name=user_name, user_email=to_email,
            subject=subject, events_count=events_count, fetch_days=fetch_days,
            status='failed', error_message=error_msg
        )
        return False
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(f"❌ {error_msg}")
        log_email_sent(
            user_id=user_id, user_name=user_name, user_email=to_email,
            subject=subject, events_count=events_count, fetch_days=fetch_days,
            status='failed', error_message=error_msg
        )
        return False

def send_email_to_users(user_ids=None, broadcast_from_user_id=None, include_admins=True, fetch_days_ahead=None):
    print("\n" + "="*60)
    if broadcast_from_user_id:
        print("📢 BROADCAST MODE")
    else:
        if fetch_days_ahead:
            print(f"🤖 PERSONALIZED MODE - Fixed {fetch_days_ahead} days")
        else:
            print("🤖 PERSONALIZED MODE - Individual preferences")
    print("="*60)
    print(f"⏰ Time: {datetime.now(pytz.UTC)}")
    print(f"🌍 Timezone: {USER_TIMEZONE}")
    print(f"👥 Include Admins: {include_admins}")
    print("="*60 + "\n")
    
    if user_ids:
        users = User.query.filter(User.id.in_(user_ids)).all()
        print(f"👥 Sending to {len(users)} selected user(s)")
    else:
        users = get_all_users()
        print(f"👥 Total users in database: {len(users)}")
        
        if not include_admins:
            users = [u for u in users if not u.is_admin()]
            print(f"👤 Filtered to {len(users)} regular users")
    
    if not users:
        print("⚠️ No users found")
        return {'total': 0, 'success': 0, 'failed': 0}
    
    broadcast_events = None
    broadcast_user_name = None
    broadcast_fetch_days = fetch_days_ahead or 7
    
    if broadcast_from_user_id:
        broadcast_user = User.query.get(broadcast_from_user_id)
        if broadcast_user:
            print(f"\n📢 Fetching events from: {broadcast_user.name}")
            broadcast_events = fetch_user_calendar_events(broadcast_from_user_id, broadcast_user.email, broadcast_fetch_days)
            broadcast_user_name = broadcast_user.name
            
            if broadcast_events is None:
                print(f"❌ Failed to fetch broadcast events")
                return {'total': len(users), 'success': 0, 'failed': len(users)}
            
            print(f"✅ Will broadcast {len(broadcast_events)} events\n")
    
    results = {
        'total': len(users),
        'success': 0,
        'failed': 0
    }
    
    for user in users:
        print(f"\n{'='*60}")
        print(f"👤 Sending to: {user.name} ({user.email})")
        
        if fetch_days_ahead:
            user_fetch_days = fetch_days_ahead
            print(f"📅 Using FIXED days: {user_fetch_days}")
        else:
            user_fetch_days = user.fetch_days or 7
            print(f"📅 Using USER preference: {user_fetch_days} days")
        
        print(f"{'='*60}")
        
        try:
            if broadcast_from_user_id and broadcast_events is not None:
                events = broadcast_events
                summary_name = f"{broadcast_user_name}'s Schedule"
                print(f"📢 Using broadcast events")
            else:
                events = fetch_user_calendar_events(user.id, user.email, user_fetch_days)
                summary_name = user.name
                
                if events is None:
                    print(f"❌ Failed to fetch events for {user.email}")
                    
                    log_email_sent(
                        user_id=user.id,
                        user_email=user.email,
                        user_name=user.name,
                        subject=f"📅 Calendar Summary - {datetime.now(pytz.UTC).strftime('%B %d, %Y')}",
                        status='failed',
                        error_message='Failed to fetch calendar events',
                        events_count=0,
                        fetch_days=user_fetch_days
                    )
                    
                    results['failed'] += 1
                    continue
            
            summary_html = generate_ai_summary(events, summary_name, user_fetch_days)
            
            if broadcast_from_user_id:
                subject = f"📅 Team Calendar Update - {datetime.now(pytz.UTC).strftime('%B %d, %Y')}"
            else:
                subject = f"📅 Your {user_fetch_days}-Day Calendar Summary - {datetime.now(pytz.UTC).strftime('%B %d, %Y')}"
            
            email_sent = send_email(
                to_email=user.email,
                subject=subject,
                html_content=summary_html,
                user_id=user.id,
                user_name=user.name,
                events_count=len(events) if events else 0,
                fetch_days=user_fetch_days
            )
            
            if email_sent:
                print(f"✅ Successfully sent to {user.email}")
                results['success'] += 1
            else:
                print(f"❌ Email failed for {user.email}")
                results['failed'] += 1
                
        except Exception as e:
            print(f"❌ Error processing {user.email}: {str(e)}")
            
            log_email_sent(
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
                subject=f"📅 Calendar Summary - {datetime.now(pytz.UTC).strftime('%B %d, %Y')}",
                status='failed',
                error_message=str(e),
                events_count=0,
                fetch_days=user_fetch_days
            )
            
            results['failed'] += 1
    
    print("\n" + "="*60)
    print("📊 EXECUTION SUMMARY")
    print("="*60)
    print(f"Total Recipients: {results['total']}")
    print(f"✅ Success: {results['success']}")
    print(f"❌ Failed: {results['failed']}")
    print("="*60 + "\n")
    
    return results


def run_daily_summary_agent(broadcast_mode=False, send_to_admins=False, fetch_days_ahead=7):
    if broadcast_mode:
        admin_user = User.query.filter_by(role='admin').first()
        if admin_user:
            return send_email_to_users(
                user_ids=None, 
                broadcast_from_user_id=admin_user.id,
                include_admins=send_to_admins,
                fetch_days_ahead=fetch_days_ahead
            )
        else:
            print("❌ No admin found for broadcast")
            return {'total': 0, 'success': 0, 'failed': 0}
    else:
        return send_email_to_users(
            user_ids=None, 
            broadcast_from_user_id=None,
            include_admins=send_to_admins,
            fetch_days_ahead=fetch_days_ahead
        )
def test_email_with_real_calendar(fetch_days_ahead=7):
    print("\n" + "="*60)
    print("🧪 TESTING EMAIL WITH REAL CALENDAR DATA")
    print("="*60 + "\n")
    
    from database import User
    user = User.query.first()
    
    if not user:
        print("❌ No user found. Please login first.")
        return False
    
    print(f"👤 Testing with user: {user.name} ({user.email})")
    
    events = fetch_user_calendar_events(user.id, user.email, fetch_days_ahead)
    
    if events is None:
        print("❌ Failed to fetch calendar events")
        return False
    
    print(f"✅ Found {len(events)} event(s)")
    
    summary_html = generate_ai_summary(events, user.name, fetch_days_ahead)
    test_email_addr = EMAIL_USER
    
    if not test_email_addr:
        print("❌ Please set EMAIL_USER in .env file")
        return False
    
    subject = "🧪 TEST - Your Real Calendar Summary"
    
    success = send_email(
        to_email=test_email_addr,
        subject=subject,
        html_content=summary_html,
        user_id=user.id,
        user_name=user.name,
        events_count=len(events),
        fetch_days=fetch_days_ahead
    )
    
    if success:
        print("\n✅ Test email sent successfully!")
        print(f"📧 Check inbox: {test_email_addr}")
    else:
        print("\n❌ Test email failed!")
        print("\n⚠️ COMMON ISSUES:")
        print("1. Gmail scope missing - User must re-login")
        print("2. Check main.py SCOPES includes: 'https://www.googleapis.com/auth/gmail.send'")
        print("3. Delete tokens.db and re-authenticate")
    
    return success


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🔧 AGENT.PY - FIXED VERSION")
    print("="*60)
    print("\n✅ Fixes Applied:")
    print("   1. Gemini model fallback (gemini-pro first)")
    print("   2. Gmail scope 403 error detection")
    print("   3. Proper error messages")
    print("\n⚠️ TO FIX YOUR ERROR:")
    print("   1. Logout from your app")
    print("   2. Delete tokens.db file")
    print("   3. Login again (will request Gmail send scope)")
    print("\n" + "="*60)