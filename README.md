# Schedule.AI

Project Overview
The Smart Calendar Assistant is an intelligent email automation system built with Flask, Google Calendar API, and Gemini AI.
Its purpose is to fetch each user’s calendar events, summarize them into a professional, well-formatted email using AI, and send that email automatically or on schedule.
This system supports both personalized summaries (each user gets their own events) and broadcast summaries (one admin’s events are shared with everyone).
All activity is tracked in an SQLite database, and the entire process is fully automated via APScheduler.
Key technologies include:
•	Flask (Backend Framework) for web interface and user authentication.
•	Google OAuth 2.0 for secure login and calendar access.
•	SQLAlchemy ORM for persistent database storage.
•	Gemini AI (Google Generative AI) for automatic event summarization.
•	APScheduler for daily and scheduled job automation.
________________________________________
Google Cloud Console Setup (OAuth & API Configuration)
To enable Google Calendar access and authentication, you must configure your Google Cloud Console and create an OAuth 2.0 client.
Follow these steps carefully before running the Smart Calendar Assistant.
Step-by-Step Configuration
1.	Sign in to Google Cloud Console
o	Go to: https://console.cloud.google.com
o	Log in with your Google account.
o	Click on the project dropdown → Create a new project (e.g., Smart Calendar Assistant).
2.	Enable APIs
o	In the left sidebar, open APIs & Services → Library.
o	Search and enable these APIs:
• Google Calendar API
• Gmail API
• Google People API (optional but recommended for profile info)

3.	Create OAuth 2.0 Credentials
o	Go to APIs & Services → Credentials → + Create Credentials → OAuth client ID.
o	If prompted, first configure the OAuth Consent Screen (next step).
o	Choose Web application as the Application type.
o	Name it something like Smart Calendar Web Client.
4.	Configure OAuth Consent Screen
o	Under APIs & Services → OAuth consent screen, choose:
• User Type: External
• App name: Smart Calendar Assistant
• User support email: your Gmail address
• Add authorized domains (e.g., localhost or your production domain)
• Add yourself as a test user
• Save and continue through the scopes section.
5.	Add Authorized Redirect URIs
o	In your OAuth client configuration, under Authorized redirect URIs,           add: http://127.0.0.1:5000/callback
(or your deployed domain’s callback URL if hosted online)
6.	Copy Credentials
o	After saving, you’ll see:
• Client ID
• Client Secret
o	Copy both and paste them into your .env file as:
o	GOOGLE_CLIENT_ID=your_client_id_here
o	GOOGLE_CLIENT_SECRET=your_client_secret_here
o	REDIRECT_URI=http://127.0.0.1:5000/callback
7.	Enable Test Users (Optional)
o	If your app is in “Testing” mode, add user email addresses under Test Users in the OAuth Consent Screen.
o	Only these users will be able to sign in during development.
8.	Verify API Quotas
o	Go to IAM & Admin → Quotas and ensure the Google Calendar API is active with default quota limits.
9.	Run Flask Application
o	Start your Flask app and open http://127.0.0.1:5000/login.
o	Sign in with the Google account added as a test user.
o	The system will automatically generate and store tokens securely in the database.
________________________________________
.env File Example
FLASK_SECRET_KEY=your_flask_secret_key
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
REDIRECT_URI=http://127.0.0.1:5000/callback
GEMINI_API_KEY=your_gemini_api_key
USER_TIMEZONE=Asia/Karachi
________________________________________
Important Notes
•	Gmail accounts require an App Password (if 2FA is enabled).
•	Ensure “Less secure apps” access is disabled use app passwords instead.
•	Keep your .env file private; never upload it to GitHub.
•	If you deploy the project online, update the redirect URI accordingly in Google Cloud Console.
Virtual Environment & Requirements Installation
Before running the Smart Calendar Assistant, make sure your system has Python 3.10+ installed. This project uses a virtual environment (venv) to keep dependencies isolated and organized.
Follow these steps based on whether you already have a virtual environment or not:
Step 1: Create a Virtual Environment (if not already created)
•	If you don’t have a virtual environment yet, create one inside your project folder.
For Windows:
Command: python -m venv venv
Command: venv\Scripts\activate
 Step 2: Install Dependencies
•	Once your virtual environment is activated, install all required libraries using the requirements.txt file.
•	Command: pip install -r requirements.txt
________________________________________
1. database.py — Data Layer (Models & Persistence)
The database.py file defines and manages all database models and helper functions using SQLAlchemy.
It serves as the backbone for storing user data, authentication tokens, scheduled jobs, and email logs.
Core Models
1.	User
o	Stores basic user details like email, name, and role.
o	Each user can be either an admin or a regular user.
o	Includes a fetch_days field (default 7), allowing users to control how many future days their summaries cover.
o	Relationship: linked to multiple Token and EmailLog records.
2.	Token
o	Manages OAuth access and refresh tokens in encrypted form.
o	Each token belongs to a specific user (user_id).
o	Automatically stores expiry and last update timestamps.
o	Uses the encrypt_token() and decrypt_token() functions (from encryption.py) for security.
3.	ScheduledJob
o	Keeps track of automated or manually scheduled jobs (via APScheduler).
o	Fields include job_id, scheduled_time, status, and created_by.
o	Used mainly by admin users to manage future email broadcasts.
4.	EmailLog
o	Logs every email sent or failed.
o	Records status (success/failed), error_message, events_count, and fetch_days.
o	Helpful for performance monitoring and troubleshooting.
________________________________________
Helper Functions Overview
•	User Management:
o	get_or_create_user(email, name) → Finds or creates a new user.
o	Automatically assigns admin role if the email is listed in .env → ADMIN_EMAILS.
•	Token Handling:
o	save_token(), get_user_tokens(), is_token_expired() manage encrypted Google OAuth tokens.
o	save_token() refreshes expiry and updates records securely.
•	Job Handling:
o	Functions like create_scheduled_job() and update_job_status() track scheduled email jobs.
o	Admins can cancel jobs anytime with cancel_scheduled_job().

•	Email Logging:
o	log_email_sent() stores every email attempt.
o	get_email_logs() retrieves logs, optionally filtered by date range.
o	get_logs_stats() summarizes total, success, and failed email stats.
o	delete_old_logs() keeps the database optimized by removing outdated logs.
________________________________________
2. agent.py — AI Email Automation Engine
The agent.py file is the core automation logic of the Smart Calendar Assistant.
It fetches events from users’ Google Calendars, generates AI-based summaries, builds professional HTML email templates, and sends them automatically using the Gmail API all actions are logged in the database for transparency.

Fetching Calendar Events
Function: fetch_user_calendar_events(user_id, user_email, fetch_days_ahead=7)
This function retrieves each user’s upcoming calendar events from Google Calendar using their valid OAuth 2.0 access token.
Key Operations:
•	Calculates the time range (timeMin → now, timeMax → future date based on fetch_days_ahead).
•	Sends a GET request to the Google Calendar API.
•	Handles timezone conversions via pytz.
•	Returns structured event objects ready for AI summarization.
•	If an error occurs (e.g., expired or revoked token), the function returns None and logs the issue.
AI-Powered Event Summarization
Function: generate_ai_summary(events, user_name, fetch_days_ahead=7)
This function transforms raw calendar data into a polished, concise HTML summary using Google Gemini (gemini-pro).
Prompt Highlights:
•	Groups events by date with friendly weekday headers.
•	Uses 12-hour time format for better readability.
•	Writes in a formal yet friendly tone (under 300 words).
•	Includes clear formatting for titles, times, and descriptions.
If Gemini AI fails or returns incomplete content, the system gracefully switches to a fallback manual template.
Email Template Creation
Function: create_professional_email(...), Builds a modern HTML layout for the email summary.
Template Features:
•	Gradient header titled “Weekly Calendar Summary.”
•	Personalized greeting (e.g., “Good Morning, John!”).
•	Responsive event cards showing date, title, and location.
•	Clean closing footer with attribution to “Smart Calendar Assistant.”
•	If no events exist, a friendly message like “No Events Scheduled.”
Sending Emails via Gmail API
Function: send_email_via_gmail_api(to_email, subject, html_content, user_id, ...), This function sends emails using the Gmail API with OAuth 2.0.
Process Flow:
1.	Builds a MIME email message (email.mime.text.MIMEText).
2.	Encodes it in Base64 for Gmail API compatibility.
3.	Uses the user’s OAuth token to authenticate and send the message via the endpoint:
4.	https://gmail.googleapis.com/gmail/v1/users/me/messages/send
5.	Logs the email result (success/failure) into the database.
Automation & Execution
1.	send_email_to_users()
o	Iterates through all registered users.
o	Generates and sends personalized AI summaries.
o	Supports two modes:
	Individual Mode: Each user receives their own calendar summary.
	Broadcast Mode: The admin’s events are sent to all users.
o	Logs every send attempt for monitoring.
2.	run_daily_summary_agent()
o	Main entry point for automated or scheduled runs.
o	Automatically chooses between broadcast or individual mode.
o	Integrated with APScheduler for daily and timed jobs.
3.	test_email_with_real_calendar()
o	Used for development testing with real Google Calendar data.
o	Verifies AI summary generation and Gmail API sending.
________________________________________
3. main.py — Web App, Dashboard, and Scheduler
The main.py file integrates everything into a web server built on Flask. It handles user authentication, dashboards, background scheduling, and REST APIs.

Google OAuth 2.0 Integration
•	Routes /login and /callback manage Google sign-in using OAuth2Session.
•	After successful login:
o	The system fetches user info (email, name).
o	Creates or updates a user record in the database.
o	Encrypts and saves tokens.
Users can then access their dashboard, while admins get redirected to the admin panel.
Admin Dashboard
Admins can view:
•	All registered users and their token status.
•	Pending and completed scheduled jobs.
•	Each user’s email preferences (fetch days).
•	Activity logs showing success/failure of emails.
The admin panel also allows scheduling new emails, canceling pending ones, and exporting logs as CSV.
Automated Scheduling (APScheduler)
The system includes a background scheduler that:
•	Runs the run_daily_summary_agent() function every midnight (UTC).
•	Allows admins to manually schedule emails at any custom future time using the web dashboard.
•	Records each schedule in the database under ScheduledJob.
API Endpoints Summary
•	/api/send_to_selected → Send email summaries to specific users.
•	/api/schedule_email → Schedule future email delivery.
•	/api/export_logs_csv → Export logs to a downloadable CSV file.
•	/api/test_token/<id> → Validate a user’s token status.
•	/api/save_user_preference → Update a user’s preferred summary range.
•	/api/cancel_job → Cancel an upcoming scheduled job.
Other Features
•	/logs → Displays detailed email logs with filters.
•	/trigger_agent → Allows manual email runs.
•	/debug → Shows internal user/token states (admin-only).
•	/logout → Clears the current session safely.
________________________________________4.functions.py Core Utility & Admin Control Layer
The functions.py module contains all backend helper and management functions that power the Smart Calendar Assistant’s admin dashboard, logging system, scheduling engine, and automation triggers. It cleanly separates reusable logic from main.py, allowing the web interface to stay lightweight and maintainable.
Access Control
Function: admin_required(f)
•	Flask decorator to restrict specific routes to admin users only.
•	Redirects unauthorized users to the index or shows an access-denied message.
•	Ensures only verified admins can schedule, cancel, or export email jobs.
Dashboard Data & Analytics
Function: get_dashboard_data(admin_timezone)
•	Aggregates user and job statistics for the admin dashboard.
•	Returns:
o	Total users, admins, and pending jobs.
o	User list with token validity and fetch-day preferences.
o	Upcoming and completed scheduled jobs (converted to admin’s timezone).
•	Uses models from database.py (e.g., User, ScheduledJob) for data retrieval.
________________________________________
Email Logs & Export
Function: get_logs_data(admin_timezone, start_date=None, end_date=None, limit=500)
•	Retrieves email sending logs with full timezone conversion.
•	Combines stats (success, failed) with detailed message history.
•	Enables filtering by date range and record limits.
Function: export_logs_to_csv(admin_timezone, start_date=None, end_date=None, limit=5000)
•	Exports email log entries into downloadable CSV format.
•	Includes columns such as:
o	Date, Time, User, Subject, Status, Event Count, Error Message.
•	Automatically adjusts times to the admin’s timezone for clarity.
User Preferences
Function: save_user_preferences(user_id, fetch_days=None)
•	Validates and saves user-specific preferences such as number of days to fetch events ahead.
•	Enforces valid range (1–365 days).
•	Returns confirmation messages or validation errors.
Email Automation Controls
Function: send_emails_to_selected_users(user_ids, fetch_days=7)
•	Triggers AI-generated email summaries for selected users.
•	Calls agent.send_email_to_users() internally, which now uses the Gmail API (OAuth) for sending.
•	Logs success/failure counts for admin review.
Function: schedule_email_job(scheduler, app, datetime_str, admin_timezone, user_ids, fetch_days, created_by_user_id)
•	Creates a future-scheduled email job using APScheduler.
•	Automatically converts admin’s local datetime to UTC before storing.
•	Each job is tracked in the database with a unique job ID.
•	Executes send_email_to_users() at the scheduled time.
•	Updates the job status (completed, failed, cancelled) in real-time.
Function: cancel_job(scheduler, job_id)
•	Cancels an upcoming scheduled email delivery.
•	Removes the job from APScheduler and updates its status to “cancelled” in the database.
Function: clear_completed_jobs()
•	Deletes completed, failed, or cancelled jobs from the database to maintain performance.
•	Returns a count of removed records.
Debugging & Diagnostics
Function: get_debug_info(admin_timezone)
•	Generates a complete textual debug report of all users and tokens.
•	Shows:
o	User IDs, roles, fetch-day preferences.
o	Token status (VALID or EXPIRED).
•	Useful for troubleshooting user authentication or token refresh issues.
5. encryption.py (Expected Role)
Although not provided, this module securely encrypts and decrypts tokens before storing them in the database.
Typically, it uses a library like cryptography.fernet or AES encryption with a key from .env.
Example structure:
from cryptography.fernet import Fernet
key = os.getenv("ENCRYPTION_KEY")
cipher = Fernet(key)
def encrypt_token(data): return cipher.encrypt(data.encode())
def decrypt_token(data): return cipher.decrypt(data).decode()
This ensures Google tokens remain unreadable even if the database is leaked.
6. utils.py — OAuth & Utility Manager
The utils.py module handles all Google OAuth 2.0 authentication, token management, and utility operations required by the Smart Calendar Assistant. It ensures that every Google API request whether for Calendar or Gmail always uses a valid access token and refreshes it automatically when needed.
Token Management & Validation
Function: refresh_access_token(refresh_token)
•	Exchanges the user’s refresh token for a new access token using the Google OAuth 2.0 endpoint.
•	Updates the user’s token record in the database.
•	Handles invalid or revoked tokens gracefully by returning None and logging the failure.
Function: get_valid_token(user_id)
•	Checks the stored token’s expiration time.
•	If expired, automatically calls refresh_access_token() to get a new one.
•	Returns a valid access token ready to be used by Google APIs (Calendar & Gmail).
Constant: GOOGLE_CLIENT_ID
•	Loaded from the .env file.
•	Acts as a global constant to authenticate users across all OAuth flows in the project.
System Workflow Overview
1.	User Authentication:
The user signs in with Google via OAuth 2.0.
The system securely stores their access and refresh tokens in the database.
2.	Scheduled Automation:
The daily scheduler triggers the agent to fetch each user’s Google Calendar events using their valid tokens.
3.	AI Summary Generation:
The Gemini AI (gemini-pro) model summarizes upcoming events into a human-friendly weekly digest.
4.	Email Delivery via Gmail API:
Emails are sent securely using the Gmail API — fully authenticated through each user’s OAuth tokens.
No SMTP servers or App Passwords are required.
5.	Logging & Monitoring:
Every action (token refresh, event fetch, email send) is logged in the database.
Admins can review logs, check user activity, and monitor scheduled jobs through the admin dashboard.
________________________________________
Conclusion
This project is a complete automation pipeline for calendar-based communication, combining:
•	Real-time event data from Google Calendar.
•	Natural language generation using Gemini AI.
•	Database logging and analytics for transparency.
•	Secure token management and encryption for user safety.
•	A modern admin interface for control and scheduling.
