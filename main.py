import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, redirect, session, url_for, jsonify, render_template
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
import pytz

# Import database aur helper functions
from database import (
    db, get_or_create_user, save_token, get_user_tokens, 
    is_token_expired, get_user_by_id, create_scheduled_job,
    update_job_status, get_all_scheduled_jobs, cancel_scheduled_job, User, ScheduledJob
)

# Import from utils.py
from utils import refresh_access_token, get_valid_token, GOOGLE_CLIENT_ID as GOOGLE_CLIENT_ID_UTIL

# Load environment variables
load_dotenv()

# ============================================
# FLASK APP CONFIGURATION
# ============================================

app = Flask(__name__)

# Flask secret key 
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Database configuration
db_path = os.path.join(os.getcwd(), 'tokens.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Database ko app ke saath initialize karo
db.init_app(app)

# ============================================
# 🌍 TIMEZONE CONFIGURATION (from .env)
# ============================================

USER_TIMEZONE = os.getenv("USER_TIMEZONE", "UTC")
FETCH_DAYS_AHEAD = int(os.getenv("FETCH_DAYS_AHEAD", "7"))

# ============================================
# 🕒 SCHEDULER SETUP
# ============================================

from agent import run_daily_summary_agent, send_email_to_users

scheduler = BackgroundScheduler(timezone=pytz.UTC)

def scheduled_job():
    """Midnight UTC job"""
    print(f"\n{'='*60}")
    print(f"⏰ SCHEDULED JOB TRIGGERED at {datetime.now(pytz.UTC)}")
    print(f"{'='*60}\n")
    
    with app.app_context():
        run_daily_summary_agent()

# Midnight UTC scheduler
scheduler.add_job(
    func=scheduled_job,
    trigger=CronTrigger(hour=0, minute=0, timezone=pytz.UTC),
    id='daily_summary_job',
    name='Send Daily Calendar Summary',
    replace_existing=True
)

scheduler.start()

# ============================================
# GOOGLE OAUTH CONFIGURATION
# ============================================

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://www.googleapis.com/oauth2/v4/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"

SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.readonly"
]

# ✅ FIXED: Dynamic redirect URI based on environment
# Production mein environment variable se lega
# Development mein localhost use karega
REDIRECT_URI = os.getenv("REDIRECT_URI")

# If REDIRECT_URI is not set, auto-detect based on environment
if not REDIRECT_URI:
    if os.getenv("FLASK_ENV") == "production":
        # Production auto-detect (Railway/Heroku/etc)
        REDIRECT_URI = os.getenv("RAILWAY_STATIC_URL", "https://scheduleai-production.up.railway.app") + "/callback"
    else:
        # Local development fallback
        REDIRECT_URI = "http://127.0.0.1:5000/callback"

print(f"🔗 OAuth Redirect URI: {REDIRECT_URI}")

# ============================================
# 🛡️ ADMIN CHECK DECORATOR
# ============================================

def admin_required(f):
    """Decorator: Admin-only access"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        
        user = get_user_by_id(session['user_id'])
        if not user or not user.is_admin():
            return render_template('error.html', 
                error_title="🚫 Access Denied",
                error_message="You don't have admin privileges to access this page."
            ), 403
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# ROUTES
# ============================================

@app.route("/")
def index():
    """Home page"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    return render_template('index.html')


@app.route("/login")
def login():
    """Google OAuth login"""
    google = OAuth2Session(GOOGLE_CLIENT_ID, scope=SCOPES, redirect_uri=REDIRECT_URI)
    
    authorization_url, state = google.authorization_url(
        AUTHORIZATION_BASE_URL,
        access_type="offline",
        prompt="consent"
    )
    
    session['oauth_state'] = state
    return redirect(authorization_url)


@app.route("/callback")
def callback():
    """OAuth callback handler"""
    try:
        google = OAuth2Session(
            GOOGLE_CLIENT_ID, 
            redirect_uri=REDIRECT_URI, 
            state=session.get('oauth_state')
        )
        
        token = google.fetch_token(
            TOKEN_URL,
            client_secret=GOOGLE_CLIENT_SECRET,
            authorization_response=request.url
        )
        
        print("\n" + "="*60)
        print("✅ Token received from Google")
        print("="*60)
        
        # Get user info
        user_info_response = google.get(USERINFO_URL)
        
        if user_info_response.status_code != 200:
            return "Error fetching user info from Google", 500
        
        user_info = user_info_response.json()
        user_email = user_info.get('email')
        user_name = user_info.get('name', 'Unknown')
        
        print(f"📧 User Email: {user_email}")
        print(f"👤 User Name: {user_name}")
        
        # Create/find user
        user = get_or_create_user(user_email, user_name)
        
        # Save tokens
        save_token(
            user_id=user.id,
            access_token=token.get('access_token'),
            refresh_token=token.get('refresh_token'),
            expires_in=token.get('expires_in', 3600)
        )
        
        print(f"💾 Tokens saved for user_id: {user.id} ({user.role})")
        print("="*60 + "\n")
        
        session['user_id'] = user.id
        session.pop('oauth_token', None)
        session.pop('oauth_state', None)
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"❌ Error in callback: {str(e)}")
        return f"<h1>Authentication Error</h1><p>{str(e)}</p><a href='/'>Go Home</a>", 500


@app.route("/dashboard")
def dashboard():
    """Main dashboard - redirects based on role"""
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user = get_user_by_id(session['user_id'])
    
    if not user:
        session.clear()
        return redirect(url_for('index'))
    
    # Admin → admin panel
    if user.is_admin():
        return redirect(url_for('admin_panel'))
    
    # User → user dashboard
    return render_template('dashboard_user.html', user=user)


@app.route("/admin")
@admin_required
def admin_panel():
    """Admin panel with scheduling"""
    users = User.query.all()
    admins_count = sum(1 for u in users if u.is_admin())
    users_count = len(users) - admins_count
    
    # Get scheduled jobs
    scheduled_jobs = get_all_scheduled_jobs()
    pending_jobs_count = sum(1 for j in scheduled_jobs if j.status == 'pending')
    
    # Prepare jobs data with user info
    jobs_data = []
    user_tz = pytz.timezone(USER_TIMEZONE)
    
    for job in scheduled_jobs:
        creator = get_user_by_id(job.created_by) if job.created_by else None
        user_count = len(job.user_ids.split(',')) if job.user_ids else 'All users'
        
        # Convert UTC time back to user timezone for display
        scheduled_time_utc = pytz.UTC.localize(job.scheduled_time) if job.scheduled_time.tzinfo is None else job.scheduled_time
        scheduled_time_local = scheduled_time_utc.astimezone(user_tz)
        
        jobs_data.append({
            'job_id': job.job_id,
            'scheduled_time': scheduled_time_local,  # Now in user timezone
            'status': job.status,
            'user_count': user_count,
            'creator_name': creator.name if creator else 'Unknown'
        })
    
    # Prepare users data with token status
    users_data = []
    sorted_users = sorted(users, key=lambda u: (0 if u.is_admin() else 1, u.name.lower()))
    
    for user in sorted_users:
        users_data.append({
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'is_admin': user.is_admin(),
            'token_valid': not is_token_expired(user.id)
        })
    
    return render_template('dashboard_admin.html',
        users=users_data,
        total_users=len(users),
        admins_count=admins_count,
        users_count=users_count,
        scheduled_jobs=jobs_data,
        pending_jobs_count=pending_jobs_count,
        timezone=USER_TIMEZONE,
        fetch_days=FETCH_DAYS_AHEAD
    )


# ============================================
# 📌 API ENDPOINTS
# ============================================

@app.route("/api/send_to_selected", methods=['POST'])
@admin_required
def api_send_to_selected():
    """Send email to multiple users"""
    data = request.json
    user_ids = data.get('user_ids', [])
    
    if not user_ids:
        return jsonify({'error': 'No users selected'}), 400
    
    try:
        user_ids = [int(uid) for uid in user_ids]
        result = send_email_to_users(user_ids=user_ids, broadcast_from_user_id=None, include_admins=True)
        return jsonify({
            'success': True,
            'message': f'✅ Emails sent! Success: {result["success"]}, Failed: {result["failed"]}'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route("/api/test_token/<int:user_id>")
@admin_required
def api_test_token(user_id):
    """Test user token validity"""
    try:
        token_data = get_valid_token(user_id)
        if token_data:
            return jsonify({'success': True, 'message': '✅ Token is valid!'})
        else:
            return jsonify({'success': False, 'message': '❌ Token expired. Re-authentication needed.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route("/api/schedule_email", methods=['POST'])
@admin_required
def api_schedule_email():
    """Schedule email for later"""
    data = request.json
    datetime_str = data.get('datetime')
    user_ids = data.get('user_ids', [])
    
    if not datetime_str:
        return jsonify({'error': 'Date & time required'}), 400
    
    try:
        # Parse and convert to UTC
        scheduled_dt = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M')
        user_tz = pytz.timezone(USER_TIMEZONE)
        scheduled_dt = user_tz.localize(scheduled_dt)
        scheduled_dt_utc = scheduled_dt.astimezone(pytz.UTC)
        
        # Check future time
        if scheduled_dt_utc <= datetime.now(pytz.UTC):
            return jsonify({
                'success': False,
                'message': '⚠️ Please select a future date & time!'
            }), 400
        
        # Create job ID
        job_id = f"scheduled_{int(scheduled_dt_utc.timestamp())}_{session.get('user_id')}"
        
        # Job function
        def send_scheduled_emails():
            with app.app_context():
                try:
                    print(f"\n📅 EXECUTING SCHEDULED JOB: {job_id}")
                    
                    if user_ids:
                        result = send_email_to_users(
                            user_ids=[int(uid) for uid in user_ids],
                            broadcast_from_user_id=None,
                            include_admins=True
                        )
                    else:
                        result = send_email_to_users(
                            user_ids=None,
                            broadcast_from_user_id=None,
                            include_admins=False
                        )
                    
                    update_job_status(job_id, 'completed', datetime.utcnow())
                    print(f"✅ Scheduled job completed: {result}")
                    
                except Exception as e:
                    print(f"❌ Scheduled job failed: {str(e)}")
                    update_job_status(job_id, 'failed', datetime.utcnow())
        
        # Add to scheduler
        scheduler.add_job(
            func=send_scheduled_emails,
            trigger=DateTrigger(run_date=scheduled_dt_utc),
            id=job_id,
            name=f'Scheduled Email @ {scheduled_dt}',
            replace_existing=True
        )
        
        # Save to database
        create_scheduled_job(
            job_id=job_id,
            scheduled_time=scheduled_dt_utc,
            user_ids=user_ids if user_ids else [],
            created_by=session.get('user_id')
        )
        
        recipient_text = f"{len(user_ids)} selected user(s)" if user_ids else "all users"
        
        return jsonify({
            'success': True,
            'message': f'✅ Email scheduled for {scheduled_dt.strftime("%Y-%m-%d %H:%M")} {USER_TIMEZONE}!\n👥 Recipients: {recipient_text}'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route("/api/cancel_job", methods=['POST'])
@admin_required
def api_cancel_job():
    """Cancel scheduled job"""
    data = request.json
    job_id = data.get('job_id')
    
    if not job_id:
        return jsonify({'error': 'Job ID required'}), 400
    
    try:
        scheduler.remove_job(job_id)
        cancel_scheduled_job(job_id)
        
        return jsonify({'success': True, 'message': '✅ Job cancelled!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route("/api/clear_completed_jobs", methods=['POST'])
@admin_required
def api_clear_completed_jobs():
    """Clear all completed/failed/cancelled jobs from database"""
    try:
        # Get all completed/failed/cancelled jobs
        completed_jobs = ScheduledJob.query.filter(
            ScheduledJob.status.in_(['completed', 'failed', 'cancelled'])
        ).all()
        
        count = len(completed_jobs)
        
        # Delete them
        for job in completed_jobs:
            db.session.delete(job)
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'✅ Cleared {count} completed/failed/cancelled job(s)!'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route("/trigger_agent")
@admin_required
def trigger_agent():
    """Manual trigger for all users"""
    print("\n" + "="*60)
    print("📘 MANUAL AGENT TRIGGER")
    print("="*60 + "\n")
    
    try:
        results = send_email_to_users(user_ids=None, broadcast_from_user_id=None, include_admins=False)
        
        return render_template('success.html',
            title="✅ Emails Sent!",
            message="Each user received their own calendar events",
            stats=results
        )
        
    except Exception as e:
        return render_template('error.html',
            error_title="❌ Agent Error",
            error_message=str(e)
        )


@app.route("/logout")
def logout():
    """Logout and clear session"""
    user_id = session.get('user_id')
    if user_id:
        user = get_user_by_id(user_id)
        if user:
            print(f"🚪 {user.role.upper()} {user.email} logged out")
    
    session.clear()
    return redirect(url_for('index'))


@app.route("/debug")
@admin_required
def debug_view():
    """Debug view - Admin only"""
    users = User.query.all()
    
    output = []
    output.append("=" * 60)
    output.append("DATABASE DEBUG VIEW")
    output.append("=" * 60)
    output.append(f"\nTotal Users: {len(users)}\n")
    output.append(f"🌍 Timezone: {USER_TIMEZONE}")
    output.append(f"📅 Fetch Days Ahead: {FETCH_DAYS_AHEAD}\n")
    
    for user in users:
        output.append("-" * 60)
        output.append(f"User ID: {user.id}")
        output.append(f"Email: {user.email}")
        output.append(f"Name: {user.name}")
        output.append(f"Role: {user.role.upper()}")
        
        tokens = get_user_tokens(user.id)
        if tokens:
            is_exp = is_token_expired(user.id)
            status = "EXPIRED" if is_exp else "VALID"
            output.append(f"Token Status: {status}")
        else:
            output.append("Token Status: NO TOKEN")
        
        output.append("")
    
    output.append("=" * 60)
    
    return "<pre>" + "\n".join(output) + "</pre>"


# ============================================
# APP INITIALIZATION
# ============================================

if __name__ == "__main__":
    # For development mode
    if os.getenv("FLASK_ENV") == "development":
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
        
        with app.app_context():
            db.create_all()
            print("\n" + "=" * 60)
            print("✅ Database tables ready!")
            print("=" * 60)
        
        port = int(os.getenv("PORT", "5000"))
        
        print("\n🚀 Flask Development Server Starting...")
        print("📊 Database: tokens.db")
        print("🔐 Encryption: Enabled")
        print("⏰ Scheduler: Active")
        print(f"🌍 Timezone: {USER_TIMEZONE}")
        print(f"📅 Fetch Days: {FETCH_DAYS_AHEAD}")
        print(f"🔗 OAuth Redirect: {REDIRECT_URI}")
        print(f"🌐 URL: http://127.0.0.1:{port}")
        print("\n" + "=" * 60 + "\n")
        
        app.run(port=port, debug=True, use_reloader=False)
    
    # For production mode with Waitress
    else:
        from waitress import serve
        
        with app.app_context():
            db.create_all()
            print("\n" + "=" * 60)
            print("✅ Database tables ready!")
            print("=" * 60)
        
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "8080"))
        threads = int(os.getenv("WAITRESS_THREADS", "4"))
        
        print("\n" + "=" * 60)
        print("🚀 Starting Production Server with Waitress")
        print("=" * 60)
        print(f"📊 Database: tokens.db")
        print(f"🔐 Encryption: Enabled")
        print(f"⏰ Scheduler: Active")
        print(f"🌍 Timezone: {USER_TIMEZONE}")
        print(f"📅 Fetch Days: {FETCH_DAYS_AHEAD}")
        print(f"🔗 OAuth Redirect: {REDIRECT_URI}")
        print(f"🌐 Host: {host}")
        print(f"🔌 Port: {port}")
        print(f"🧵 Threads: {threads}")
        print("=" * 60 + "\n")
        
        serve(app, host=host, port=port, threads=threads)
