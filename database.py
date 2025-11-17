from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from encryption import encrypt_token, decrypt_token
import os

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    role = db.Column(db.String(50), default='user')  
    fetch_days = db.Column(db.Integer, default=7)  
    # ❌ TIMEZONE FIELD REMOVED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    tokens = db.relationship('Token', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.email} - {self.role}>'
    
    def is_admin(self):
        return self.role == 'admin'


class Token(db.Model):
    __tablename__ = 'tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    access_token = db.Column(db.LargeBinary, nullable=False)
    refresh_token = db.Column(db.LargeBinary, nullable=True)
    
    expires_at = db.Column(db.DateTime, nullable=False)
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Token user_id={self.user_id}>'


class ScheduledJob(db.Model):
    __tablename__ = 'scheduled_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(100), unique=True, nullable=False)  
    scheduled_time = db.Column(db.DateTime, nullable=False) 
    status = db.Column(db.String(50), default='pending')  
    user_ids = db.Column(db.Text)  
    created_by = db.Column(db.Integer, db.ForeignKey('users.id')) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<ScheduledJob {self.job_id} @ {self.scheduled_time}>'


class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user_email = db.Column(db.String(255), nullable=False)
    user_name = db.Column(db.String(255))
    subject = db.Column(db.Text)
    status = db.Column(db.String(50))
    error_message = db.Column(db.Text)
    events_count = db.Column(db.Integer, default=0)
    fetch_days = db.Column(db.Integer, default=7)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', backref='email_logs')
    
    def __repr__(self):
        return f'<EmailLog {self.user_email} - {self.status} @ {self.sent_at}>'


def get_admin_emails():
    admin_emails_str = os.getenv("ADMIN_EMAILS", "")
    if not admin_emails_str:
        return []
    return [email.strip().lower() for email in admin_emails_str.split(',')]


def get_or_create_user(email, name):
    user = User.query.filter_by(email=email).first()
    admin_emails = get_admin_emails()
    
    if not user:
        role = 'admin' if email.lower() in admin_emails else 'user'
        user = User(email=email, name=name, role=role)
        db.session.add(user)
        db.session.commit()
        print(f"[+] New {role.upper()} created: {email}")
    else:
        expected_role = 'admin' if email.lower() in admin_emails else 'user'
        if user.role != expected_role:
            user.role = expected_role
            db.session.commit()
            print(f"[~] Role updated to {expected_role.upper()} for: {email}")
        else:
            print(f"[+] Existing {user.role.upper()} found: {email}")
    
    return user


def save_token(user_id, access_token, refresh_token, expires_in):
    token_record = Token.query.filter_by(user_id=user_id).first()
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    
    if token_record:
        token_record.access_token = encrypt_token(access_token)
        if refresh_token:  
            token_record.refresh_token = encrypt_token(refresh_token)
        token_record.expires_at = expires_at
        token_record.updated_at = datetime.utcnow()
        print(f"[~] Token updated for user_id: {user_id}")
    else:
        token_record = Token(
            user_id=user_id,
            access_token=encrypt_token(access_token),
            refresh_token=encrypt_token(refresh_token) if refresh_token else None,
            expires_at=expires_at
        )
        db.session.add(token_record)
        print(f"[+] New token saved for user_id: {user_id}")
    
    db.session.commit()


def get_user_tokens(user_id):
    token_record = Token.query.filter_by(user_id=user_id).first()
    
    if not token_record:
        return None
    
    return {
        'access_token': decrypt_token(token_record.access_token),
        'refresh_token': decrypt_token(token_record.refresh_token) if token_record.refresh_token else None,
        'expires_at': token_record.expires_at
    }


def is_token_expired(user_id):
    token_record = Token.query.filter_by(user_id=user_id).first()
    
    if not token_record:
        return True  
    
    return datetime.utcnow() > token_record.expires_at


def get_all_users():
    return User.query.all()


def get_user_by_id(user_id):
    return User.query.get(user_id)


def create_scheduled_job(job_id, scheduled_time, user_ids, created_by):
    job = ScheduledJob(
        job_id=job_id,
        scheduled_time=scheduled_time,
        user_ids=','.join(map(str, user_ids)) if user_ids else '',
        created_by=created_by,
        status='pending'
    )
    db.session.add(job)
    db.session.commit()
    return job


def update_job_status(job_id, status, completed_at=None):
    job = ScheduledJob.query.filter_by(job_id=job_id).first()
    if job:
        job.status = status
        if completed_at:
            job.completed_at = completed_at
        db.session.commit()


def get_pending_jobs():
    return ScheduledJob.query.filter_by(status='pending').all()


def get_all_scheduled_jobs():
    return ScheduledJob.query.order_by(ScheduledJob.created_at.desc()).all()


def cancel_scheduled_job(job_id):
    job = ScheduledJob.query.filter_by(job_id=job_id).first()
    if job:
        job.status = 'cancelled'
        db.session.commit()
        return True
    return False


def save_user_preference(user_id, fetch_days=None):
    """Save only fetch_days preference (timezone removed)"""
    user = User.query.get(user_id)
    if user:
        if fetch_days is not None:
            user.fetch_days = fetch_days
            print(f"[+] Fetch days saved for user {user_id}: {fetch_days} days")
        
        db.session.commit()
        return True
    return False


def get_user_preference(user_id):
    """Get only fetch_days preference (timezone removed)"""
    user = User.query.get(user_id)
    if user:
        return {
            'fetch_days': user.fetch_days or 7
        }
    return {'fetch_days': 7}


def log_email_sent(user_id, user_email, user_name, subject, status, error_message=None, events_count=0, fetch_days=7):
    try:
        log = EmailLog(
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            subject=subject,
            status=status,
            error_message=error_message,
            events_count=events_count,
            fetch_days=fetch_days,
            sent_at=datetime.utcnow()
        )
        db.session.add(log)
        db.session.commit()
        return log
    except Exception as e:
        print(f"[!] Failed to log email: {str(e)}")
        db.session.rollback()
        return None


def get_email_logs(start_date=None, end_date=None, limit=100):
    query = EmailLog.query
    
    if start_date:
        query = query.filter(EmailLog.sent_at >= start_date)
    
    if end_date:
        end_date_extended = end_date + timedelta(days=1)
        query = query.filter(EmailLog.sent_at < end_date_extended)
    
    return query.order_by(EmailLog.sent_at.desc()).limit(limit).all()


def get_logs_stats(start_date=None, end_date=None):
    query = EmailLog.query
    
    if start_date:
        query = query.filter(EmailLog.sent_at >= start_date)
    
    if end_date:
        end_date_extended = end_date + timedelta(days=1)
        query = query.filter(EmailLog.sent_at < end_date_extended)
    
    total = query.count()
    success = query.filter_by(status='success').count()
    failed = query.filter_by(status='failed').count()
    
    return {
        'total': total,
        'success': success,
        'failed': failed,
        'success_rate': round((success / total * 100) if total > 0 else 0, 2)
    }


def delete_old_logs(days_to_keep=30):
    cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
    
    try:
        deleted = EmailLog.query.filter(EmailLog.sent_at < cutoff_date).delete()
        db.session.commit()
        print(f"[+] Deleted {deleted} old log(s) from database")
        return deleted
    except Exception as e:
        print(f"[!] Failed to delete old logs: {str(e)}")
        db.session.rollback()
        return 0