"""
Email Verification System for Bisque Registration

This module provides email verification functionality for user registration.
Now uses the unified Bisque email service for all email operations.

Features:
- Unified SMTP configuration via bq.core.mail
- Secure verification token generation
- Email template rendering via unified service
- Optional email verification (configurable)
"""

import os
import logging
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

try:
    from tg import config
    TG_AVAILABLE = True
except ImportError:
    TG_AVAILABLE = False
    config = None

try:
    from bq.core.model import DBSession
    from bq.data_service.model.tag_model import Tag
    BQ_MODELS_AVAILABLE = True
except ImportError:
    BQ_MODELS_AVAILABLE = False
    DBSession = None
    Tag = None

try:
    from bq.core.mail import get_email_service, is_email_available
    EMAIL_SERVICE_AVAILABLE = True
except ImportError:
    EMAIL_SERVICE_AVAILABLE = False
    get_email_service = None
    is_email_available = None

log = logging.getLogger("bq.registration.email")

class EmailVerificationError(Exception):
    """Custom exception for email verification errors"""
    pass

class EmailVerificationService:
    """Service for handling email verification using the unified email system"""
    
    def __init__(self):
        # Check if all required dependencies are available
        if not EMAIL_SERVICE_AVAILABLE:
            raise ImportError("Unified email service not available - email verification disabled")
        if not TG_AVAILABLE:
            raise ImportError("TurboGears not available - email verification disabled")
        if not BQ_MODELS_AVAILABLE:
            raise ImportError("Bisque models not available - email verification disabled")
            
        self.email_service = get_email_service()
        self.verification_enabled = self._is_verification_enabled()
    
    def _is_verification_enabled(self):
        """Check if email verification is enabled in configuration"""
        # Check environment variable first (for Docker/container deployments)
        env_enabled = os.environ.get('BISQUE_EMAIL_VERIFICATION_ENABLED', 'false').lower()
        if env_enabled in ['true', '1', 'yes', 'on']:
            return True
        
        # Check main Bisque configuration
        config_enabled = config.get('bisque.registration.email_verification.enabled', False)
        if config_enabled:
            return True
        
        # Check legacy configurations for backward compatibility
        legacy_enabled = config.get('registration.email_verification.enabled', False) or \
                        config.get('email_verification.enabled', False)
        return bool(legacy_enabled)
    
    def is_available(self):
        """Check if email verification is available (SMTP configured and verification enabled)"""
        available = self.email_service.is_available() and self.verification_enabled
        if not available:
            if not self.email_service.is_available():
                log.debug("Email verification unavailable: Email service not configured")
            if not self.verification_enabled:
                log.debug("Email verification unavailable: verification disabled in config")
        return available
    
    def validate_configuration(self):
        """Validate the current email verification configuration and return status"""
        status = {
            'available': False,
            'smtp_configured': self.email_service.is_available(),
            'verification_enabled': self.verification_enabled,
            'errors': [],
            'warnings': []
        }
        
        # Check unified email service configuration
        if not self.email_service.is_available():
            config_summary = self.email_service.config.get_config_summary()
            if not config_summary.get('smtp_host'):
                status['errors'].append("SMTP host not configured")
            if not config_summary.get('default_from_email'):
                status['errors'].append("From email address not configured")
            if not config_summary['configured']:
                status['errors'].append("Email service not properly configured")
        
        # Check verification enabled
        if not self.verification_enabled:
            status['warnings'].append("Email verification is disabled - users will be auto-verified")
        
        status['available'] = self.email_service.is_available() and self.verification_enabled and len(status['errors']) == 0
        
        return status
    
    def test_smtp_connection(self):
        """Test SMTP connection using the unified email service"""
        if not self.email_service.is_available():
            return {
                'success': False,
                'error': 'Email service not configured'
            }
        
        return self.email_service.test_connection()
    
    def generate_verification_token(self, email, username):
        """Generate a secure verification token"""
        # Create a secure random token
        random_token = secrets.token_urlsafe(32)
        
        # Add timestamp and user info for additional security
        timestamp = datetime.now(timezone.utc).isoformat()
        token_data = f"{random_token}:{email}:{username}:{timestamp}"
        
        # Hash the token data
        token_hash = hashlib.sha256(token_data.encode()).hexdigest()
        
        return f"{random_token}.{token_hash[:16]}"
    
    def verify_token(self, token, email, username, max_age_hours=24):
        """Verify a verification token"""
        try:
            if '.' not in token:
                return False
            
            random_token, token_hash = token.split('.', 1)
            
            # Reconstruct the token data (we need to check multiple timestamps)
            # Since we don't store the exact timestamp, we'll check a range
            now = datetime.now(timezone.utc)
            for hours_ago in range(max_age_hours + 1):
                check_time = now - timedelta(hours=hours_ago)
                # Check multiple timestamp formats for robustness
                for minutes_ago in range(60):
                    check_time_exact = check_time - timedelta(minutes=minutes_ago)
                    timestamp = check_time_exact.isoformat()
                    token_data = f"{random_token}:{email}:{username}:{timestamp}"
                    expected_hash = hashlib.sha256(token_data.encode()).hexdigest()[:16]
                    
                    if expected_hash == token_hash:
                        return True
            
            return False
        except Exception as e:
            log.error(f"Token verification error: {e}")
            return False
    
    def get_smtp_config(self):
        """Get SMTP configuration from environment or TurboGears config"""
        # Prefer environment variables (for Docker/container deployments)
        if os.environ.get('BISQUE_SMTP_HOST'):
            return {
                'host': os.environ.get('BISQUE_SMTP_HOST'),
                'port': int(os.environ.get('BISQUE_SMTP_PORT', 587)),
                'username': os.environ.get('BISQUE_SMTP_USER'),
                'password': os.environ.get('BISQUE_SMTP_PASSWORD'),
                'use_tls': os.environ.get('BISQUE_SMTP_TLS', 'true').lower() in ['true', '1', 'yes'],
                'from_email': os.environ.get('BISQUE_SMTP_FROM_EMAIL', os.environ.get('BISQUE_SMTP_USER')),
                'from_name': os.environ.get('BISQUE_SMTP_FROM_NAME', 'Bisque System')
            }
        
        # Try main Bisque configuration with email verification settings
        if config.get('registration.email_verification.smtp.host'):
            return {
                'host': config.get('registration.email_verification.smtp.host'),
                'port': int(config.get('registration.email_verification.smtp.port', 587)),
                'username': config.get('registration.email_verification.smtp.username'),
                'password': config.get('registration.email_verification.smtp.password'),
                'use_tls': config.get('registration.email_verification.smtp.use_tls', True),
                'from_email': config.get('registration.email_verification.smtp.from_email', config.get('registration.email_verification.smtp.username', 'noreply@localhost')),
                'from_name': config.get('registration.email_verification.smtp.from_name', 'Bisque System')
            }
        
        # Fallback to legacy TurboGears config
        return {
            'host': config.get('smtp.host'),
            'port': int(config.get('smtp.port', 587)),
            'username': config.get('smtp.username'),
            'password': config.get('smtp.password'),
            'use_tls': config.get('smtp.use_tls', True),
            'from_email': config.get('smtp.from_email', config.get('smtp.username')),
            'from_name': config.get('smtp.from_name', 'Bisque System')
        }
    
    def send_verification_email(self, email, username, fullname, verification_token, base_url):
        """Send verification email to user"""
        if not self.is_available():
            raise EmailVerificationError("Email verification not available (SMTP not configured or verification disabled)")
        
        smtp_config = self.get_smtp_config()
        
        # Create verification URL
        verification_url = f"{base_url}/registration/verify_email?token={verification_token}&email={email}"
        
        # Create email content
        subject = "Verify your Bisque account"
        
        # HTML email template
        html_body = f"""
        <html>
        <head></head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h1 style="color: #007bff; margin: 0;">Bisque - Email Verification</h1>
                </div>
                
                <div style="background: white; padding: 30px; border-radius: 8px; border: 1px solid #dee2e6;">
                    <h2 style="color: #333; margin-top: 0;">Welcome to Bisque, {fullname}!</h2>
                    
                    <p>Thank you for registering for a Bisque account. To complete your registration and activate your account, please verify your email address by clicking the button below:</p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{verification_url}" 
                           style="background-color: #007bff; color: white; padding: 12px 30px; text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold;">
                            Verify Email Address
                        </a>
                    </div>
                    
                    <p>If the button doesn't work, you can copy and paste this link into your browser:</p>
                    <p style="word-break: break-all; background: #f8f9fa; padding: 10px; border-radius: 4px; font-family: monospace;">
                        {verification_url}
                    </p>
                    
                    <hr style="margin: 30px 0; border: none; border-top: 1px solid #dee2e6;">
                    
                    <div style="font-size: 14px; color: #666;">
                        <p><strong>Account Details:</strong></p>
                        <ul>
                            <li>Username: {username}</li>
                            <li>Email: {email}</li>
                        </ul>
                        
                        <p><strong>Important:</strong></p>
                        <ul>
                            <li>This verification link will expire in 24 hours</li>
                            <li>You cannot sign in until your email is verified</li>
                            <li>If you didn't create this account, please ignore this email</li>
                        </ul>
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 20px; color: #666; font-size: 12px;">
                    <p>This email was sent by the Bisque Bio-Image Analysis Platform</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_body = f"""
        Welcome to Bisque, {fullname}!

        Thank you for registering for a Bisque account. To complete your registration 
        and activate your account, please verify your email address by visiting:

        {verification_url}

        Account Details:
        - Username: {username}
        - Email: {email}

        Important:
        - This verification link will expire in 24 hours
        - You cannot sign in until your email is verified
        - If you didn't create this account, please ignore this email

        This email was sent by the Bisque Bio-Image Analysis Platform
        """
        
        try:
            # Create message
            msg = MimeMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = formataddr((smtp_config['from_name'], smtp_config['from_email']))
            msg['To'] = email
            
            # Attach both plain text and HTML versions
            text_part = MimeText(text_body, 'plain')
            html_part = MimeText(html_body, 'html')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            # Send email with better error handling
            try:
                with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
                    if smtp_config['use_tls']:
                        server.starttls()
                    server.login(smtp_config['username'], smtp_config['password'])
                    server.send_message(msg)
                
                log.info(f"Verification email sent successfully to {email}")
                return True
                
            except smtplib.SMTPAuthenticationError as e:
                log.error(f"SMTP authentication failed for {smtp_config['username']}: {e}")
                raise EmailVerificationError(f"SMTP authentication failed. Check username/password: {e}")
            except smtplib.SMTPConnectError as e:
                log.error(f"Failed to connect to SMTP server {smtp_config['host']}:{smtp_config['port']}: {e}")
                raise EmailVerificationError(f"Failed to connect to SMTP server: {e}")
            except smtplib.SMTPRecipientsRefused as e:
                log.error(f"SMTP server refused recipient {email}: {e}")
                raise EmailVerificationError(f"Email address rejected by server: {e}")
            except smtplib.SMTPException as e:
                log.error(f"SMTP error sending email to {email}: {e}")
                raise EmailVerificationError(f"SMTP error: {e}")
            
        except EmailVerificationError:
            # Re-raise EmailVerificationError as-is
            raise
        except Exception as e:
            log.error(f"Unexpected error sending verification email to {email}: {e}")
            raise EmailVerificationError(f"Failed to send verification email: {e}")
    
    def test_smtp_connection(self):
        """Test SMTP connection without sending email"""
        if not self.smtp_enabled:
            return {'success': False, 'error': 'SMTP not configured'}
        
        try:
            smtp_config = self.get_smtp_config()
            with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
                if smtp_config['use_tls']:
                    server.starttls()
                server.login(smtp_config['username'], smtp_config['password'])
            
            return {'success': True, 'message': 'SMTP connection successful'}
            
        except smtplib.SMTPAuthenticationError as e:
            return {'success': False, 'error': f'SMTP authentication failed: {e}'}
        except smtplib.SMTPConnectError as e:
            return {'success': False, 'error': f'Failed to connect to SMTP server: {e}'}
        except Exception as e:
            return {'success': False, 'error': f'SMTP connection error: {e}'}
    
    def mark_user_as_verified(self, bq_user):
        """Mark a user's email as verified"""
        try:
            # Add email_verified tag
            verified_tag = Tag(parent=bq_user)
            verified_tag.name = 'email_verified'
            verified_tag.value = 'true'
            verified_tag.owner = bq_user
            DBSession.add(verified_tag)
            
            # Add verification timestamp
            verified_time_tag = Tag(parent=bq_user)
            verified_time_tag.name = 'email_verified_at'
            verified_time_tag.value = datetime.now(timezone.utc).isoformat()
            verified_time_tag.owner = bq_user
            DBSession.add(verified_time_tag)
            
            DBSession.flush()
            log.info(f"User {bq_user.resource_name} marked as email verified")
            return True
            
        except Exception as e:
            log.error(f"Failed to mark user as verified: {e}")
            return False
    
    def is_user_verified(self, bq_user):
        """Check if a user's email is verified"""
        try:
            verified_tag = DBSession.query(Tag).filter(
                Tag.parent == bq_user,
                Tag.name == 'email_verified',
                Tag.value == 'true'
            ).first()
            
            return verified_tag is not None
            
        except Exception as e:
            log.error(f"Failed to check user verification status: {e}")
            return False
