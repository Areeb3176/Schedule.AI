import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, redirect, session, url_for, jsonify, render_template
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from database import (
    db, get_or_create_user, save_token, get_user_by_id, User
)

from utils import GOOGLE_CLIENT_ID as GOOGLE_CLIENT_ID_UTIL
from agent import run_daily_summary_agent

from functions import (
    admin_required, get_dashboard_data, get_logs_data, export_logs_to_csv,
    save_user_preferences, send_emails_to_selected_users,
    schedule_email_job, cancel_job, clear_completed_jobs, get_debug_info
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

db_path = os.path.join(os.getcwd(), 'tokens.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

USER_TIMEZONE = os.getenv("USER_TIMEZONE", "UTC")

scheduler = BackgroundScheduler(timezone=pytz.UTC)

def scheduled_job():
    """Midnight UTC job"""
    print(f"\n{'='*60}")
    print(f"[*] SCHEDULED JOB TRIGGERED at {datetime.now(pytz.UTC)}")
    print(f"{'='*60}\n")
    
    with app.app_context():
        run_daily_summary_agent()

scheduler.add_job(
    func=scheduled_job,
    trigger=CronTrigger(hour=0, minute=0, timezone=pytz.UTC),
    id='daily_summary_job',
    name='Send Daily Calendar Summary',
    replace_existing=True
)

scheduler.start()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://www.googleapis.com/oauth2/v4/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose"
]

REDIRECT_URI = os.getenv("REDIRECT_URI", "http://127.0.0.1:5000/callback")

print(f"[*] OAuth Redirect URI: {REDIRECT_URI}")
print(f"[*] OAuth Scopes: {len(SCOPES)} scopes configured")


@app.route("/")
def index():
    """Home page"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    return render_template('index.html')


@app.route("/login")
def login():
    """Google OAuth login"""
    google = OAuth2Session(
        GOOGLE_CLIENT_ID, 
        scope=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    authorization_url, state = google.authorization_url(
        AUTHORIZATION_BASE_URL,
        access_type="offline",
        prompt="consent",
        include_granted_scopes='true'
    )
    
    session['oauth_state'] = state
    
    print("\n" + "="*60)
    print("🔐 OAuth Login Initiated")
    print("="*60)
    print(f"Scopes requested: {len(SCOPES)}")
    for i, scope in enumerate(SCOPES, 1):
        scope_name = scope.split('/')[-1] if '/' in scope else scope
        print(f"  {i}. {scope_name}")
    print("="*60 + "\n")
    
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
        print("[+] Token received from Google")
        print("="*60)
        print(f"Access Token: {'✅ Received' if token.get('access_token') else '❌ Missing'}")
        print(f"Refresh Token: {'✅ Received' if token.get('refresh_token') else '❌ Missing'}")
        print(f"Expires In: {token.get('expires_in', 0)} seconds")
        
        token_scope = token.get('scope', '')
        gmail_send_present = 'gmail.send' in token_scope
        print(f"Gmail Send Scope: {'✅ GRANTED' if gmail_send_present else '❌ MISSING'}")
        print("="*60 + "\n")
        
        if not gmail_send_present:
            print("⚠️ WARNING: Gmail send scope NOT granted!")
            print("⚠️ User will NOT be able to send emails!")
            print("⚠️ This usually means:")
            print("    1. Scope not in SCOPES list")
            print("    2. Gmail API not enabled in Google Cloud")
            print("    3. App not verified by Google")
        
        user_info_response = google.get(USERINFO_URL)
        
        if user_info_response.status_code != 200:
            return "Error fetching user info from Google", 500
        
        user_info = user_info_response.json()
        user_email = user_info.get('email')
        user_name = user_info.get('name', 'Unknown')
        
        print(f"[*] User Email: {user_email}")
        print(f"[*] User Name: {user_name}")
        
        user = get_or_create_user(user_email, user_name)
        
        save_token(
            user_id=user.id,
            access_token=token.get('access_token'),
            refresh_token=token.get('refresh_token'),
            expires_in=token.get('expires_in', 3600)
        )
        
        print(f"[+] Tokens saved for user_id: {user.id} ({user.role})")
        print("="*60 + "\n")
        
        session['user_id'] = user.id
        session.pop('oauth_token', None)
        session.pop('oauth_state', None)
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"[!] Error in callback: {str(e)}")
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
    
    if user.is_admin():
        return redirect(url_for('admin_panel'))
    
    return render_template('dashboard_user.html', user=user)


@app.route("/admin")
@admin_required
def admin_panel():
    """Admin panel with scheduling and user preferences"""
    dashboard_data = get_dashboard_data(USER_TIMEZONE)
    admin_tz = pytz.timezone(USER_TIMEZONE)
    
    return render_template('dashboard_admin.html',
        users=dashboard_data['users'],
        total_users=dashboard_data['total_users'],
        admins_count=dashboard_data['admins_count'],
        users_count=dashboard_data['users_count'],
        scheduled_jobs=dashboard_data['scheduled_jobs'],
        pending_jobs_count=dashboard_data['pending_jobs_count'],
        timezone=USER_TIMEZONE,
        fetch_days=7,
        now=datetime.now(admin_tz).strftime('%Y-%m-%d %H:%M:%S')
    )


@app.route("/logs")
@admin_required
def view_logs():
    """View email logs with date filtering"""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    start_date = None
    end_date = None
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except:
            pass
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        except:
            pass
    
    logs_data = get_logs_data(USER_TIMEZONE, start_date=start_date, end_date=end_date)
    
    return render_template('logs.html',
        logs=logs_data['logs'],
        stats=logs_data['stats'],
        start_date=start_date_str or '',
        end_date=end_date_str or '',
        timezone=USER_TIMEZONE,
        total_logs=logs_data['total_logs']
    )


@app.route("/api/export_logs_csv")
@admin_required
def export_logs_csv():
    """Export logs to CSV file"""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    start_date = None
    end_date = None
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except:
            pass
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        except:
            pass
    
    csv_content, filename = export_logs_to_csv(USER_TIMEZONE, start_date=start_date, end_date=end_date)
    
    return csv_content, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename={filename}'
    }


@app.route("/api/save_user_preference", methods=['POST'])
def api_save_user_preference():
    """Save user's preferences"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'success': False, 'message': 'Invalid JSON data'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'JSON parse error: {str(e)}'}), 400
    
    fetch_days = data.get('fetch_days')
    # ❌ REMOVED: timezone = data.get('timezone')
    
    user = get_user_by_id(session['user_id'])
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    # ✅ FIXED: Only pass fetch_days (timezone parameter removed)
    success, message = save_user_preferences(user.id, fetch_days=fetch_days)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 500
    

@app.route("/api/send_to_selected", methods=['POST'])
@admin_required
def api_send_to_selected():
    """Send email to multiple users"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid JSON data'}), 400
    except Exception as e:
        return jsonify({'error': f'JSON parse error: {str(e)}'}), 400
    
    user_ids = data.get('user_ids', [])
    fetch_days = data.get('fetch_days', 7)
    
    success, message = send_emails_to_selected_users(user_ids, fetch_days)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': f'❌ Error: {message}'}), 500


@app.route("/api/test_token/<int:user_id>")
@admin_required
def api_test_token(user_id):
    """Test user token validity"""
    try:
        from utils import get_valid_token
        token_data = get_valid_token(user_id)
        if token_data:
            return jsonify({'success': True, 'message': '✅ Token is valid!'})
        else:
            return jsonify({'success': False, 'message': '❌ Token expired'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'❌ Error: {str(e)}'}), 500


@app.route("/api/schedule_email", methods=['POST'])
@admin_required
def api_schedule_email():
    """Schedule email for later"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid JSON data'}), 400
    except Exception as e:
        return jsonify({'error': f'JSON parse error: {str(e)}'}), 400
    
    datetime_str = data.get('datetime')
    user_ids = data.get('user_ids', [])
    fetch_days = data.get('fetch_days', 7)
    
    if not datetime_str:
        return jsonify({'error': 'Date & time required'}), 400
    
    success, message = schedule_email_job(
        scheduler, 
        app, 
        datetime_str, 
        USER_TIMEZONE, 
        user_ids, 
        fetch_days, 
        session.get('user_id')
    )
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 400


@app.route("/api/cancel_job", methods=['POST'])
@admin_required
def api_cancel_job():
    """Cancel scheduled job"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid JSON data'}), 400
    except Exception as e:
        return jsonify({'error': f'JSON parse error: {str(e)}'}), 400
    
    job_id = data.get('job_id')
    
    if not job_id:
        return jsonify({'error': 'Job ID required'}), 400
    
    success, message = cancel_job(scheduler, job_id)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': f'❌ Error: {message}'}), 500


@app.route("/api/clear_completed_jobs", methods=['POST'])
@admin_required
def api_clear_completed_jobs():
    """Clear all completed/failed/cancelled jobs"""
    success, message = clear_completed_jobs()
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': f'❌ Error: {message}'}), 500


@app.route("/trigger_agent")
@admin_required
def trigger_agent():
    """Manual trigger for all users"""
    from agent import send_email_to_users
    
    fetch_days = request.args.get('days', 7, type=int)
    
    if fetch_days < 1 or fetch_days > 365:
        return render_template('error.html',
            error_title="❌ Invalid Input",
            error_message="Days must be between 1 and 365"
        )
    
    print("\n" + "="*60)
    print("[*] MANUAL AGENT TRIGGER")
    print("="*60 + "\n")
    
    try:
        results = send_email_to_users(
            user_ids=None, 
            broadcast_from_user_id=None, 
            include_admins=False,
            fetch_days_ahead=fetch_days
        )
        
        return render_template('success.html',
            title=f"✅ Emails Sent ({fetch_days} days)!",
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
    user_id = session.get('user_id')
    if user_id:
        user = get_user_by_id(user_id)
        if user:
            print(f"[*] {user.role.upper()} {user.email} logged out")
    
    session.clear()
    return redirect(url_for('index'))


@app.route("/debug")
@admin_required
def debug_view():
    debug_info = get_debug_info(USER_TIMEZONE)
    return "<pre>" + debug_info + "</pre>"


if __name__ == "__main__":
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    with app.app_context():
        db.create_all()
        print("\n" + "=" * 60)
        print("[+] Database tables ready!")
        print("=" * 60)
    
    port = int(os.getenv("PORT", "5000"))
    
    print("\n[*] Flask Development Server Starting...")
    print("[*] Database: tokens.db")
    print("[*] Encryption: Enabled")
    print("[*] Scheduler: Active")
    print(f"[*] Timezone: {USER_TIMEZONE}")
    print(f"[*] OAuth Redirect: {REDIRECT_URI}")
    print(f"[*] URL: http://127.0.0.1:{port}")
    print("\n" + "=" * 60 + "\n")
    
    app.run(port=port, debug=True, use_reloader=False)