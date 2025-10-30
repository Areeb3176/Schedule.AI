from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from encryption import encrypt_token, decrypt_token
import os

# Database object
db = SQLAlchemy()


# DATABASE MODELS

class User(db.Model):
    """
    User table - User ki basic info store karta hai
    """
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    role = db.Column(db.String(50), default='user')  # 'admin' ya 'user'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship: Ek user ke paas tokens ho sakte hain
    tokens = db.relationship('Token', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.email} - {self.role}>'
    
    def is_admin(self):
        """Check if user is admin"""
        return self.role == 'admin'


class Token(db.Model):
    """
    Token table - User ke OAuth tokens store karta hai (encrypted form mein)
    """
    __tablename__ = 'tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Tokens encrypted form mein store honge
    access_token = db.Column(db.LargeBinary, nullable=False)
    refresh_token = db.Column(db.LargeBinary, nullable=True)
    
    # Token expiry time
    expires_at = db.Column(db.DateTime, nullable=False)
    
    # Token kab update hua
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Token user_id={self.user_id}>'


class ScheduledJob(db.Model):
    """
    Scheduled jobs table - Admin ke scheduled emails track karta hai
    """
    __tablename__ = 'scheduled_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(100), unique=True, nullable=False)  # APScheduler job ID
    scheduled_time = db.Column(db.DateTime, nullable=False)  # Kab run hoga
    status = db.Column(db.String(50), default='pending')  # pending, completed, failed, cancelled
    user_ids = db.Column(db.Text)  # Comma-separated user IDs (empty = all users)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # Admin user ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<ScheduledJob {self.job_id} @ {self.scheduled_time}>'


# DATABASE HELPER FUNCTIONS

def get_admin_emails():
    """
    .env se admin emails fetch karo (comma-separated)
    """
    admin_emails_str = os.getenv("ADMIN_EMAILS", "")
    if not admin_emails_str:
        return []
    return [email.strip().lower() for email in admin_emails_str.split(',')]


def get_or_create_user(email, name):
    """
    User ko find/create karo aur role assign karo
    """
    user = User.query.filter_by(email=email).first()
    
    # Admin emails list
    admin_emails = get_admin_emails()
    
    if not user:
        # Role determine karo
        role = 'admin' if email.lower() in admin_emails else 'user'
        
        # Naya user create karo
        user = User(email=email, name=name, role=role)
        db.session.add(user)
        db.session.commit()
        print(f"✅ New {role.upper()} created: {email}")
    else:
        # Existing user ka role update karo (agar admin list mein add hua ho)
        expected_role = 'admin' if email.lower() in admin_emails else 'user'
        if user.role != expected_role:
            user.role = expected_role
            db.session.commit()
            print(f"🔄 Role updated to {expected_role.upper()} for: {email}")
        else:
            print(f"✅ Existing {user.role.upper()} found: {email}")
    
    return user


def save_token(user_id, access_token, refresh_token, expires_in):
    """
    User ka token save/update karo (encrypted)
    """
    token_record = Token.query.filter_by(user_id=user_id).first()
    
    # Expiry time calculate karo
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    
    if token_record:
        # Existing token ko update karo
        token_record.access_token = encrypt_token(access_token)
        if refresh_token:  # Refresh token hamesha nahi milta
            token_record.refresh_token = encrypt_token(refresh_token)
        token_record.expires_at = expires_at
        token_record.updated_at = datetime.utcnow()
        print(f"🔄 Token updated for user_id: {user_id}")
    else:
        token_record = Token(
            user_id=user_id,
            access_token=encrypt_token(access_token),
            refresh_token=encrypt_token(refresh_token) if refresh_token else None,
            expires_at=expires_at
        )
        db.session.add(token_record)
        print(f"✅ New token saved for user_id: {user_id}")
    
    db.session.commit()


def get_user_tokens(user_id):
    """
    User ke tokens fetch karo (decrypted)
    """
    token_record = Token.query.filter_by(user_id=user_id).first()
    
    if not token_record:
        return None
    
    return {
        'access_token': decrypt_token(token_record.access_token),
        'refresh_token': decrypt_token(token_record.refresh_token) if token_record.refresh_token else None,
        'expires_at': token_record.expires_at
    }


def is_token_expired(user_id):
    """
    Check karo token expired hai ya nahi
    """
    token_record = Token.query.filter_by(user_id=user_id).first()
    
    if not token_record:
        return True  
    
    return datetime.utcnow() > token_record.expires_at


def get_all_users():
    """
    Sab users fetch karo
    """
    return User.query.all()


def get_user_by_id(user_id):
    """
    User ko ID se fetch karo
    """
    return User.query.get(user_id)


# SCHEDULED JOB HELPERS

def create_scheduled_job(job_id, scheduled_time, user_ids, created_by):
    """
    Naya scheduled job database mein save karo
    """
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
    """
    Job ki status update karo
    """
    job = ScheduledJob.query.filter_by(job_id=job_id).first()
    if job:
        job.status = status
        if completed_at:
            job.completed_at = completed_at
        db.session.commit()


def get_pending_jobs():
    """
    Pending jobs fetch karo
    """
    return ScheduledJob.query.filter_by(status='pending').all()


def get_all_scheduled_jobs():
    """
    All scheduled jobs fetch karo (recent first)
    """
    return ScheduledJob.query.order_by(ScheduledJob.created_at.desc()).all()


def cancel_scheduled_job(job_id):
    """
    Job ko cancel karo
    """
    job = ScheduledJob.query.filter_by(job_id=job_id).first()
    if job:
        job.status = 'cancelled'
        db.session.commit()
        return True
    return False