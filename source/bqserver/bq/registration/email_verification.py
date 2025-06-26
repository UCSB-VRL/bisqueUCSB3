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
from datetime import datetime, timedelta

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
        log.info(f"Email verification service initialized: self.email_service = {self.email_service}, verification_enabled = {self.verification_enabled}")
    
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
        timestamp = datetime.utcnow().isoformat()
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
            now = datetime.utcnow()
            
            # Check tokens generated within the last max_age_hours
            for hours_ago in range(max_age_hours + 1):
                check_time = now - timedelta(hours=hours_ago)
                for minute_offset in range(60):  # Check each minute in the hour
                    check_timestamp = (check_time - timedelta(minutes=minute_offset)).isoformat()
                    token_data = f"{random_token}:{email}:{username}:{check_timestamp}"
                    expected_hash = hashlib.sha256(token_data.encode()).hexdigest()[:16]
                    
                    if expected_hash == token_hash:
                        return True
            
            return False
            
        except Exception as e:
            log.error(f"Error verifying token: {e}")
            return False
    
    def send_verification_email(self, email, username, fullname, verification_token, base_url):
        """Send verification email using the unified email service"""
        if not self.is_available():
            return {
                'success': False,
                'error': 'Email verification service not available'
            }
        
        # Build verification URL - use verify_email endpoint with query parameters
        verification_url = f"{base_url}/registration/verify_email?token={verification_token}&email={email}"
        
        # Use the unified email service template
        context = {
            'username': username,
            'fullname': fullname,
            'email': email,
            'verification_link': verification_url
        }
        
        result = self.email_service.send_template_email(
            template_name='email_verification',
            to=email,
            context=context
        )
        
        if result['success']:
            log.info(f"Verification email sent successfully to {email}")
            return {'success': True}
        else:
            log.error(f"Failed to send verification email to {email}: {result['error']}")
            return {
                'success': False,
                'error': f"Failed to send verification email: {result['error']}"
            }
    
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
            verified_time_tag.value = datetime.utcnow().isoformat()
            verified_time_tag.owner = bq_user
            DBSession.add(verified_time_tag)
            
            DBSession.flush()
            log.info(f"User {bq_user.resource_name} marked as email verified")
            return {'success': True}
            
        except Exception as e:
            log.error(f"Failed to mark user as verified: {e}")
            return {
                'success': False,
                'error': f"Failed to mark user as verified: {e}"
            }
    
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

# Global email verification service instance
_email_verification_service = None

def get_email_verification_service():
    """Get the global email verification service instance"""
    global _email_verification_service
    if _email_verification_service is None:
        try:
            _email_verification_service = EmailVerificationService()
        except ImportError as e:
            log.warning(f"Email verification service not available: {e}")
            _email_verification_service = False  # Mark as unavailable
    return _email_verification_service if _email_verification_service is not False else None

def is_email_verification_available():
    """Check if email verification service is available"""
    service = get_email_verification_service()
    return service is not None and service.is_available()
