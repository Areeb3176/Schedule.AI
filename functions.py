from datetime import datetime
import pytz
from flask import session, request, redirect, url_for, jsonify, render_template
from functools import wraps

from database import (
    get_user_by_id, get_user_tokens, is_token_expired, 
    save_user_preference, get_email_logs, get_logs_stats,
    create_scheduled_job, update_job_status, get_all_scheduled_jobs,
    cancel_scheduled_job, ScheduledJob, User, db
)
from agent import send_email_to_users
import csv
from io import StringIO


def admin_required(f):
    """Decorator: Admin-only access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        
        user = get_user_by_id(session['user_id'])
        if not user or not user.is_admin():
            return render_template('error.html', 
                error_title="[!] Access Denied",
                error_message="You don't have admin privileges to access this page."
            ), 403
        
        return f(*args, **kwargs)
    return decorated_function


def get_dashboard_data(admin_timezone):
    """Get all users and scheduled jobs for admin dashboard"""
    users = User.query.all()
    admins_count = sum(1 for u in users if u.is_admin())
    users_count = len(users) - admins_count
    
    scheduled_jobs = get_all_scheduled_jobs()
    pending_jobs_count = sum(1 for j in scheduled_jobs if j.status == 'pending')
    
    jobs_data = []
    admin_tz = pytz.timezone(admin_timezone)
    
    for job in scheduled_jobs:
        creator = get_user_by_id(job.created_by) if job.created_by else None
        user_count = len(job.user_ids.split(',')) if job.user_ids else 'All users'
        
        scheduled_time_utc = pytz.UTC.localize(job.scheduled_time) if job.scheduled_time.tzinfo is None else job.scheduled_time
        scheduled_time_local = scheduled_time_utc.astimezone(admin_tz)
        
        jobs_data.append({
            'job_id': job.job_id,
            'scheduled_time': scheduled_time_local,
            'status': job.status,
            'user_count': user_count,
            'creator_name': creator.name if creator else 'Unknown'
        })
    
    users_data = []
    sorted_users = sorted(users, key=lambda u: (0 if u.is_admin() else 1, u.name.lower()))
    
    for user in sorted_users:
        users_data.append({
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'is_admin': user.is_admin(),
            'token_valid': not is_token_expired(user.id),
            'fetch_days': user.fetch_days or 7
        })
    
    return {
        'users': users_data,
        'total_users': len(users),
        'admins_count': admins_count,
        'users_count': users_count,
        'scheduled_jobs': jobs_data,
        'pending_jobs_count': pending_jobs_count
    }


def get_logs_data(admin_timezone, start_date=None, end_date=None, limit=500):
    """Get email logs with timezone conversion"""
    logs = get_email_logs(start_date=start_date, end_date=end_date, limit=limit)
    stats = get_logs_stats(start_date=start_date, end_date=end_date)
    
    logs_data = []
    admin_tz = pytz.timezone(admin_timezone)
    
    for log in logs:
        sent_at_utc = pytz.UTC.localize(log.sent_at) if log.sent_at.tzinfo is None else log.sent_at
        sent_at_local = sent_at_utc.astimezone(admin_tz)
        
        logs_data.append({
            'id': log.id,
            'user_name': log.user_name,
            'user_email': log.user_email,
            'subject': log.subject,
            'status': log.status,
            'error_message': log.error_message,
            'events_count': log.events_count,
            'fetch_days': log.fetch_days,
            'sent_at': sent_at_local
        })
    
    return {
        'logs': logs_data,
        'stats': stats,
        'total_logs': len(logs_data)
    }


def export_logs_to_csv(admin_timezone, start_date=None, end_date=None, limit=5000):
    """Export logs to CSV format"""
    logs = get_email_logs(start_date=start_date, end_date=end_date, limit=limit)
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ID', 'Date', 'Time', 'User Name', 'Email', 'Subject', 'Status', 'Events', 'Days', 'Error'])
    
    admin_tz = pytz.timezone(admin_timezone)
    for log in logs:
        sent_at_utc = pytz.UTC.localize(log.sent_at) if log.sent_at.tzinfo is None else log.sent_at
        sent_at_local = sent_at_utc.astimezone(admin_tz)
        
        writer.writerow([
            log.id,
            sent_at_local.strftime('%Y-%m-%d'),
            sent_at_local.strftime('%H:%M:%S'),
            log.user_name,
            log.user_email,
            log.subject,
            log.status,
            log.events_count,
            log.fetch_days,
            log.error_message or ''
        ])
    
    output.seek(0)
    filename = f"email_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return output.getvalue(), filename


def save_user_preferences(user_id, fetch_days=None):
    """Validate and save ONLY fetch_days preference"""
    if fetch_days is not None:
        try:
            fetch_days = int(fetch_days)
            if fetch_days < 1 or fetch_days > 365:
                return False, 'Days must be between 1 and 365'
        except (ValueError, TypeError):
            return False, 'Invalid days value'
    
    try:
        save_user_preference(user_id, fetch_days=fetch_days)
        message = f"✅ Fetch days saved: {fetch_days} days"
        return True, message
    except Exception as e:
        return False, str(e)


def send_emails_to_selected_users(user_ids, fetch_days=7):
    """Send emails to selected users"""
    if not user_ids:
        return False, 'No users selected'
    
    try:
        fetch_days = int(fetch_days)
        if fetch_days < 1 or fetch_days > 365:
            return False, 'Days must be between 1 and 365'
    except (ValueError, TypeError):
        return False, 'Invalid days value'
    
    try:
        user_ids = [int(uid) for uid in user_ids]
        result = send_email_to_users(
            user_ids=user_ids, 
            broadcast_from_user_id=None, 
            include_admins=True,
            fetch_days_ahead=fetch_days
        )
        message = f'✅ Emails sent! Success: {result["success"]}, Failed: {result["failed"]}'
        return True, message
    except Exception as e:
        return False, str(e)


def schedule_email_job(scheduler, app, datetime_str, admin_timezone, user_ids, fetch_days, created_by_user_id):
    """Schedule email job for future delivery"""
    try:
        fetch_days = int(fetch_days)
        if fetch_days < 1 or fetch_days > 365:
            return False, 'Days must be between 1 and 365'
    except (ValueError, TypeError):
        return False, 'Invalid days value'
    
    try:
        scheduled_dt = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M')
        admin_tz = pytz.timezone(admin_timezone)
        scheduled_dt = admin_tz.localize(scheduled_dt)
        scheduled_dt_utc = scheduled_dt.astimezone(pytz.UTC)
        
        if scheduled_dt_utc <= datetime.now(pytz.UTC):
            return False, '⚠️ Please select a future date & time!'
        
        job_id = f"scheduled_{int(scheduled_dt_utc.timestamp())}_{created_by_user_id}"
        
        def send_scheduled_emails():
            with app.app_context():
                try:
                    print(f"\n[*] EXECUTING SCHEDULED JOB: {job_id}")
                    
                    if user_ids:
                        result = send_email_to_users(
                            user_ids=[int(uid) for uid in user_ids],
                            broadcast_from_user_id=None,
                            include_admins=True,
                            fetch_days_ahead=fetch_days
                        )
                    else:
                        result = send_email_to_users(
                            user_ids=None,
                            broadcast_from_user_id=None,
                            include_admins=False,
                            fetch_days_ahead=fetch_days
                        )
                    
                    update_job_status(job_id, 'completed', datetime.utcnow())
                    print(f"[+] Scheduled job completed: {result}")
                    
                except Exception as e:
                    print(f"[!] Scheduled job failed: {str(e)}")
                    update_job_status(job_id, 'failed', datetime.utcnow())
        
        from apscheduler.triggers.date import DateTrigger
        
        scheduler.add_job(
            func=send_scheduled_emails,
            trigger=DateTrigger(run_date=scheduled_dt_utc),
            id=job_id,
            name=f'Scheduled Email @ {scheduled_dt}',
            replace_existing=True
        )
        
        create_scheduled_job(
            job_id=job_id,
            scheduled_time=scheduled_dt_utc,
            user_ids=user_ids if user_ids else [],
            created_by=created_by_user_id
        )
        
        message = f'✅ Email scheduled for {scheduled_dt.strftime("%Y-%m-%d %H:%M")} {admin_timezone}!'
        return True, message
        
    except Exception as e:
        return False, str(e)


def cancel_job(scheduler, job_id):
    """Cancel a scheduled job"""
    try:
        scheduler.remove_job(job_id)
        cancel_scheduled_job(job_id)
        return True, '✅ Job cancelled!'
    except Exception as e:
        return False, str(e)


def clear_completed_jobs():
    """Clear all completed/failed/cancelled jobs from database"""
    try:
        completed_jobs = ScheduledJob.query.filter(
            ScheduledJob.status.in_(['completed', 'failed', 'cancelled'])
        ).all()
        
        count = len(completed_jobs)
        
        for job in completed_jobs:
            db.session.delete(job)
        
        db.session.commit()
        return True, f'✅ Cleared {count} job(s)!'
        
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def get_debug_info(admin_timezone):
    """Get debug information about all users"""
    users = User.query.all()
    
    output = []
    output.append("=" * 60)
    output.append("DATABASE DEBUG VIEW")
    output.append("=" * 60)
    output.append(f"\nTotal Users: {len(users)}\n")
    output.append(f"[*] Admin Timezone: {admin_timezone}\n")
    
    for user in users:
        output.append("-" * 60)
        output.append(f"User ID: {user.id}")
        output.append(f"Email: {user.email}")
        output.append(f"Name: {user.name}")
        output.append(f"Role: {user.role.upper()}")
        output.append(f"Fetch Days: {user.fetch_days or 7}")
        
        tokens = get_user_tokens(user.id)
        if tokens:
            is_exp = is_token_expired(user.id)
            status = "EXPIRED" if is_exp else "VALID"
            output.append(f"Token Status: {status}")
        else:
            output.append("Token Status: NO TOKEN")
        
        output.append("")
    
    output.append("=" * 60)
    
    return "\n".join(output)