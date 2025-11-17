#Smart Calendar Assistant

Smart Calendar Assistant is an easy-to-use automated system that connects with your Google Calendar, summarizes upcoming events using AI, and sends a professional email to you automatically. It uses Google OAuth for secure login, Gemini AI for natural summaries, and APScheduler for daily automation.

Google Setup (Simple Guide for Beginners)

To run this project, the only required setup is creating an app inside Google Cloud Console. This app allows your system to access Google Calendar and Gmail with your permission.

First, open the Google Cloud Console and sign in with your Google account. Create a new project and give it any name you like. After the project is created, you need to enable the required Google APIs. Simply search for Calendar API and Gmail API in the API Library and enable them. These two services allow the project to read your calendar and send emails on your behalf.

Next, you will create OAuth credentials. In the “Credentials” section, choose to create an OAuth Client ID. If Google asks you to set up the OAuth Consent Screen, just enter your app name, your email, and add "localhost" as an allowed domain. Once the consent screen is saved, continue creating the OAuth client. Select “Web Application” as the type and add your redirect URL. This redirect URL is where Google will send the user back after they sign in.

When the OAuth client is created, Google will show you a Client ID and Client Secret. These two values are what connect your application to Google’s login and API services. Keep them safe, as the project will use them whenever users log in or when the system needs to refresh their tokens.

How the System Works (Simple Overview)

When a user logs in with Google, the system saves their access and refresh tokens in an encrypted format. These tokens allow the system to read their calendar and send emails securely. If a token expires, the system automatically refreshes it.

Every day, the scheduler runs in the background. It fetches each user’s upcoming events from their Google Calendar. These events are sent to Gemini AI, which writes a clean, readable, professional summary. That summary is then turned into a well-designed email and delivered through the Gmail API. All activities—calendar fetch, AI summary, email delivery—are logged in the database for transparency.

The Admin Dashboard gives full control: you can see users, view token status, check logs, schedule future emails, or manually trigger summaries whenever needed.

Core Parts of the Project

The database stores users, encrypted tokens, scheduled jobs, email logs, and user preferences.
The agent module handles AI summaries, event fetching, and email sending.
The main application uses Flask to manage login, dashboard pages, and admin tools.
Utility modules manage token refreshing and Google OAuth communication.
The encryption module ensures all sensitive data stays secure.

In Summary

If someone wants to run this project, the main thing they must do is create a Google Cloud App, enable Calendar and Gmail APIs, set up OAuth, and connect their credentials. After that, the system runs automatically—fetching events, generating AI summaries, sending emails, and keeping everything logged and visible in the admin panel.
