import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings

class EmailService:
    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_pass = settings.SMTP_PASS
        self.smtp_from = settings.SMTP_FROM
        self.frontend_url = settings.FRONTEND_URL

    def send_email(self, to_email: str, subject: str, html_body: str):
        if not self.smtp_host:
            print(f"[EmailService] SMTP not configured. Mock sending to {to_email}: {subject}")
            return
        
        msg = MIMEMultipart("alternative")
        msg['Subject'] = subject
        msg['From'] = self.smtp_from
        msg['To'] = to_email
        msg.attach(MIMEText(html_body, "html"))

        try:
            if self.smtp_port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context) as server:
                    server.login(self.smtp_user, self.smtp_pass)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if settings.SMTP_SECURE:
                        server.starttls()
                    server.login(self.smtp_user, self.smtp_pass)
                    server.send_message(msg)
            print(f"[EmailService] Email sent to {to_email}")
        except Exception as e:
            print(f"[EmailService] Failed to send email: {e}")

    def send_verification_email(self, email: str, token: str):
        verify_url = f"{self.frontend_url}/verify-email?token={token}"
        subject = "Verify your Docapture AI account"
        html_body = f"""
        <div style="max-width: 600px; margin: 0 auto; font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px; border-radius: 16px;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #fbbf24; font-size: 28px; margin: 0;">Docapture<span style="color: #fff;">AI</span></h1>
            </div>
            <h2 style="color: #fff; font-size: 22px; text-align: center; margin-bottom: 10px;">Verify your email address</h2>
            <p style="color: #94a3b8; text-align: center; margin-bottom: 30px;">Click the button below to verify your email and activate your account.</p>
            <div style="text-align: center; margin-bottom: 30px;">
                <a href="{verify_url}" style="display: inline-block; background: linear-gradient(135deg, #fbbf24, #d97706); color: #000; padding: 14px 40px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 16px;">Verify Email</a>
            </div>
            <p style="color: #64748b; font-size: 13px; text-align: center;">If you didn't create an account, you can safely ignore this email.</p>
            <hr style="border: none; border-top: 1px solid #1e293b; margin: 30px 0;">
            <p style="color: #475569; font-size: 12px; text-align: center;">&copy; 2026 Docapture AI. All rights reserved.</p>
        </div>
        """
        self.send_email(email, subject, html_body)

    def send_password_reset_email(self, email: str, user_id: str, token: str):
        reset_url = f"{self.frontend_url}/reset-password?userId={user_id}&secret={token}"
        subject = "Reset your Docapture AI password"
        html_body = f"""
        <div style="max-width: 600px; margin: 0 auto; font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px; border-radius: 16px;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #fbbf24; font-size: 28px; margin: 0;">Docapture<span style="color: #fff;">AI</span></h1>
            </div>
            <h2 style="color: #fff; font-size: 22px; text-align: center;">Reset your password</h2>
            <p style="color: #94a3b8; text-align: center; margin-bottom: 30px;">Click the button below to reset your password.</p>
            <div style="text-align: center; margin-bottom: 30px;">
                <a href="{reset_url}" style="display: inline-block; background: linear-gradient(135deg, #fbbf24, #d97706); color: #000; padding: 14px 40px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 16px;">Reset Password</a>
            </div>
            <p style="color: #64748b; font-size: 13px; text-align: center;">If you didn't request a password reset, you can safely ignore this email.</p>
        </div>
        """
        self.send_email(email, subject, html_body)

    def send_invite_email(self, email: str, name: str, token: str,
                          monthly_limit: int = None):
        """Professional invitation email asking a newly-added client to set their
        password and activate their account."""
        setup_url = f"{self.frontend_url}/set-password?token={token}"
        greeting = name.strip() if name and name.strip() else "there"
        limit_line = ""
        if monthly_limit:
            limit_line = (
                f"<tr><td style='padding:6px 0;color:#94a3b8;font-size:14px;'>"
                f"Your account is provisioned with <strong style='color:#fbbf24;'>"
                f"{monthly_limit} document credits per month</strong>.</td></tr>"
            )
        subject = "You've been invited to DoCapture AI — Activate your account"
        html_body = f"""
        <div style="max-width: 600px; margin: 0 auto; font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px; border-radius: 16px;">
            <div style="text-align: center; margin-bottom: 28px;">
                <h1 style="color: #fbbf24; font-size: 28px; margin: 0;">DoCapture<span style="color: #fff;">AI</span></h1>
            </div>
            <h2 style="color: #fff; font-size: 22px; margin: 0 0 16px;">Welcome aboard, {greeting}</h2>
            <p style="color: #cbd5e1; font-size: 15px; line-height: 1.6; margin: 0 0 16px;">
                An administrator has created a DoCapture AI account for you. To get started,
                please activate your account by setting a secure password.
            </p>
            <table style="width:100%; margin: 0 0 24px;">
                <tr><td style="padding:6px 0;color:#94a3b8;font-size:14px;">
                    <strong style="color:#e2e8f0;">Account email:</strong> {email}</td></tr>
                {limit_line}
            </table>
            <div style="text-align: center; margin: 0 0 28px;">
                <a href="{setup_url}" style="display: inline-block; background: linear-gradient(135deg, #fbbf24, #d97706); color: #000; padding: 14px 44px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 16px;">Set Your Password</a>
            </div>
            <p style="color: #94a3b8; font-size: 13px; line-height: 1.6; margin: 0 0 8px;">
                Or copy and paste this link into your browser:
            </p>
            <p style="color: #64748b; font-size: 12px; word-break: break-all; margin: 0 0 24px;">{setup_url}</p>
            <p style="color: #64748b; font-size: 13px; line-height: 1.6;">
                This activation link will expire in 48 hours for your security. If you were not
                expecting this invitation, please disregard this email.
            </p>
            <hr style="border: none; border-top: 1px solid #1e293b; margin: 28px 0;">
            <p style="color: #475569; font-size: 12px; text-align: center; margin: 0;">
                &copy; 2026 DoCapture AI. All rights reserved.
            </p>
        </div>
        """
        self.send_email(email, subject, html_body)


email_service = EmailService()
