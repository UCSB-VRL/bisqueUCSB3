import logging
from tg import expose, validate, request, redirect, flash
from tg.exceptions import HTTPFound
from bq.core.lib.base import BaseController
from bq.core.model import DBSession
from bq.core.model.auth import User

# Import email verification conditionally to avoid import errors during service loading
try:
    from bq.registration.email_verification import EmailVerificationService, EmailVerificationError
    EMAIL_VERIFICATION_AVAILABLE = True
except ImportError as e:
    EMAIL_VERIFICATION_AVAILABLE = False
    EmailVerificationService = None
    EmailVerificationError = Exception
    import logging
    logging.getLogger("bq.registration").warning(f"Email verification not available due to import error: {e}")

log = logging.getLogger("bq.registration")

class RegistrationController(BaseController):
    """
    Enhanced registration controller for Bisque user registration
    Supports: email, username, fullname, research area, institution, funding agency
    With optional email verification
    """

    service_type = "registration"

    def __init__(self):
        super().__init__()
        # Initialize email verification service safely
        self.email_service = None
        
        if not EMAIL_VERIFICATION_AVAILABLE:
            log.info("Email verification disabled - service not available due to import issues")
            return
            
        try:
            self.email_service = EmailVerificationService()
            
            # Log email verification status at startup
            config_status = self._safe_email_call("validate_configuration", )
            if config_status['available']:
                log.info("Email verification service initialized and ready")
            else:
                if not config_status['smtp_configured']:
                    log.info("Email verification disabled: SMTP not configured")
                elif not config_status['verification_enabled']:
                    log.info("Email verification disabled: feature not enabled in configuration")
                else:
                    log.warning(f"Email verification disabled due to configuration errors: {config_status['errors']}")
                log.info("Users will be automatically verified upon registration")
        except Exception as e:
            log.warning(f"Failed to initialize email verification service: {e}")
            log.info("Email verification disabled - users will be automatically verified upon registration")
            self.email_service = None

    def _safe_email_call(self, method_name, *args, **kwargs):
        """Safely call an email service method, returning default values if service unavailable"""
        log.info(f"self.email_service is {self.email_service} Calling email service method: {method_name} with args: {args}, kwargs: {kwargs}")    
        if self.email_service is None:
            # Return default values based on method name
            if method_name == 'is_available':
                return False
            elif method_name == 'validate_configuration':
                return {
                    'available': False,
                    'smtp_configured': False,
                    'verification_enabled': False,
                    'errors': ['Email verification service not initialized']
                }
            elif method_name == 'is_user_verified':
                return True  # Default to verified if no email service
            elif method_name == 'test_smtp_connection':
                return {'success': False, 'error': 'Email service not available'}
            else:
                return None
        
        try:
            method = getattr(self.email_service, method_name)
            return method(*args, **kwargs)
        except Exception as e:
            log.warning(f"Email service method {method_name} failed: {e}")
            # Return safe defaults
            if method_name == 'is_available':
                return False
            elif method_name == 'is_user_verified':
                return True  # Default to verified if check fails
            else:
                return None

    @expose('bq.registration.templates.index')
    def index(self, **kw):
        """Registration form page"""
        # Get email verification configuration status
        email_verification_status = self._safe_email_call('validate_configuration')
        email_verification_enabled = email_verification_status['available']
        
        # Log configuration status for debugging
        if email_verification_enabled:
            log.info("Email verification is enabled and properly configured")
        else:
            log.info(f"Email verification disabled - SMTP configured: {email_verification_status['smtp_configured']}, "
                    f"Verification enabled: {email_verification_status['verification_enabled']}")
            if email_verification_status['errors']:
                log.warning(f"Email verification configuration errors: {email_verification_status['errors']}")
        
        return {
            'msg': 'Welcome to user registration',
            'email_verification_enabled': email_verification_enabled,
            'email_verification_status': email_verification_status
        }

    @expose('json')
    def register(self, **kw):
        """
        Enhanced user registration endpoint
        Accepts: email, username, fullname, password, research_area, institution_affiliation, funding_agency
        """
        try:
            # Extract required fields
            email = kw.get('email', '').strip()
            username = kw.get('username', '').strip()
            fullname = kw.get('fullname', '').strip()
            password = kw.get('password', '').strip()
            research_area = kw.get('research_area', '').strip()
            institution_affiliation = kw.get('institution_affiliation', '').strip()
            funding_agency = kw.get('funding_agency', '').strip()

            # Validation
            if not email or not username or not fullname or not password:
                return {'status': 'error', 'message': 'Missing required fields: email, username, fullname, and password are required'}

            if not research_area or not institution_affiliation:
                return {'status': 'error', 'message': 'Research area and institution affiliation are required'}

            if len(password) < 6:
                return {'status': 'error', 'message': 'Password must be at least 6 characters long'}

            # Check for existing users
            existing_user_email = User.by_email_address(email)
            if existing_user_email:
                return {'status': 'error', 'message': 'A user with this email address already exists'}

            existing_user_name = User.by_user_name(username)
            if existing_user_name:
                return {'status': 'error', 'message': 'This username is already taken'}

            # Validate research area options
            valid_research_areas = [
                'Bioinformatics', 'Cell Biology', 'Developmental Biology', 'Ecology', 
                'Genetics', 'Immunology', 'Materials Science', 'Microbiology', 
                'Molecular Biology', 'Neuroscience', 'Pharmacology', 'Plant Biology', 
                'Structural Biology', 'Other'
            ]
            if research_area and research_area not in valid_research_areas:
                return {'status': 'error', 'message': f'Invalid research area. Must be one of: {", ".join(valid_research_areas)}'}

            # Validate funding agency options (optional field)
            valid_funding_agencies = [
                'NIH', 'NSF', 'DOE', 'DoD', 'NASA', 'USDA', 
                'Private_Foundation', 'Industry', 'International', 'Other', 'None', ''
            ]
            if funding_agency and funding_agency not in valid_funding_agencies:
                return {'status': 'error', 'message': f'Invalid funding agency. Must be one of: {", ".join(valid_funding_agencies)}'}

            log.info(f"Creating new user: {username} ({email})")

            # Create the core TurboGears User first
            tg_user = User(
                user_name=username,
                email_address=email,
                display_name=fullname,
                password=password
            )
            DBSession.add(tg_user)
            DBSession.flush()  # Get the TG user ID, this also triggers bquser_callback
            
            # The bquser_callback automatically creates a BQUser, so let's find it
            from bq.data_service.model import BQUser
            bq_user = DBSession.query(BQUser).filter_by(resource_name=username).first()
            if not bq_user:
                # Fallback: create BQUser manually if callback didn't work
                bq_user = BQUser(tg_user=tg_user, create_tg=False, create_store=True)
                DBSession.add(bq_user)
                DBSession.flush()
                bq_user.owner_id = bq_user.id
            
            # Now add custom tags for the extended profile information
            from bq.data_service.model.tag_model import Tag
            
            # Create all tags now that bq_user has an ID
            fullname_tag = Tag(parent=bq_user)
            fullname_tag.name = 'fullname'
            fullname_tag.value = fullname
            fullname_tag.owner = bq_user
            DBSession.add(fullname_tag)
            
            username_tag = Tag(parent=bq_user)
            username_tag.name = 'username'
            username_tag.value = username
            username_tag.owner = bq_user
            DBSession.add(username_tag)
            
            research_area_tag = Tag(parent=bq_user)
            research_area_tag.name = 'research_area'
            research_area_tag.value = research_area
            research_area_tag.owner = bq_user
            DBSession.add(research_area_tag)
            
            institution_tag = Tag(parent=bq_user)
            institution_tag.name = 'institution_affiliation'
            institution_tag.value = institution_affiliation
            institution_tag.owner = bq_user
            DBSession.add(institution_tag)
            
            # Add funding agency tag (if provided)
            if funding_agency:
                funding_tag = Tag(parent=bq_user)
                funding_tag.name = 'funding_agency'
                funding_tag.value = funding_agency
                funding_tag.owner = bq_user
                DBSession.add(funding_tag)
            
            log.info(f"Successfully created user: {username} with ID: {bq_user.resource_uniq}")
            
            # Handle email verification if enabled
            verification_message = ""
            
            # Use the same validation approach as index method
            email_verification_status = self._safe_email_call('validate_configuration')
            email_verification_available = email_verification_status.get('available', False) if email_verification_status else False
            
            log.info(f"Email verification validation: {email_verification_status}")
            log.info(f"Email verification available: {email_verification_available}")
            
            if email_verification_available:
                log.info("Email verification is enabled - sending verification email")
                try:
                    # Test SMTP connection first
                    smtp_test = self._safe_email_call("test_smtp_connection", )
                    if not smtp_test['success']:
                        log.error(f"SMTP connection test failed: {smtp_test['error']}")
                        raise EmailVerificationError(f"SMTP connection failed: {smtp_test['error']}")
                    
                    # Generate verification token
                    verification_token = self._safe_email_call("generate_verification_token",  email, username)
                    
                    # Get base URL for verification link
                    base_url = request.host_url.rstrip('/')
                    
                    # Send verification email
                    self._safe_email_call("send_verification_email",
                        email, username, fullname, verification_token, base_url
                    )
                    
                    verification_message = " A verification email has been sent to your email address. Please check your email and click the verification link to activate your account."
                    
                    # Store verification token as a tag for later verification
                    token_tag = Tag(parent=bq_user)
                    token_tag.name = 'email_verification_token'
                    token_tag.value = verification_token
                    token_tag.owner = bq_user
                    DBSession.add(token_tag)
                    
                    log.info(f"Verification email sent to {email} for user {username}")
                    
                except EmailVerificationError as e:
                    log.warning(f"Failed to send verification email to {email}: {e}")
                    verification_message = " Note: Verification email could not be sent due to email server issues, but your account was created successfully. Please contact an administrator for manual verification."
                    # Mark user as verified since email failed
                    self._safe_email_call("mark_user_as_verified",  bq_user)
                    
            else:
                # If email verification is not available, mark user as verified
                self._safe_email_call("mark_user_as_verified", bq_user)
                
                # Provide detailed logging about why verification was skipped
                if email_verification_status:
                    if not email_verification_status.get('smtp_configured', False):
                        log.info(f"Email verification skipped for {username}: SMTP not configured")
                    elif not email_verification_status.get('verification_enabled', False):
                        log.info(f"Email verification skipped for {username}: verification disabled in config")
                    elif email_verification_status.get('errors'):
                        log.info(f"Email verification skipped for {username}: configuration errors: {email_verification_status['errors']}")
                    else:
                        log.info(f"Email verification skipped for {username}: unknown reason")
                else:
                    log.warning(f"Email verification skipped for {username}: failed to get verification status")
            
            return {
                'status': 'success', 
                'message': f'Account created successfully{verification_message}',
                'user_id': bq_user.resource_uniq,
                'username': username,
                'email_verification_required': email_verification_available
            }

        except Exception as e:
            # Let TurboGears transaction manager handle rollback
            log.error(f"Registration failed for {kw.get('email', 'unknown')}: {str(e)}")
            import traceback
            log.error(f"Full traceback: {traceback.format_exc()}")
            return {'status': 'error', 'message': 'Registration failed due to server error. Please try again.'}

    @expose('json')
    def check_config(self, **kw):
        """Check email verification configuration status (admin endpoint)"""
        try:
            config_status = self._safe_email_call("validate_configuration", )
            smtp_test = None
            
            if config_status['smtp_configured']:
                smtp_test = self._safe_email_call("test_smtp_connection", )
            
            return {
                'status': 'success',
                'email_verification': config_status,
                'smtp_test': smtp_test
            }
            
        except Exception as e:
            log.error(f"Error checking email verification config: {e}")
            return {
                'status': 'error',
                'message': f'Failed to check configuration: {e}'
            }

    @expose('json')
    def confirm(self, **kw):
        """Email confirmation endpoint - placeholder for future implementation"""
        code = kw.get('code')
        return {'status': 'success', 'message': 'Email confirmation not yet implemented.'}

    @expose('json')
    def check_availability(self, **kw):
        """Check if username or email is available"""
        username = kw.get('username', '').strip()
        email = kw.get('email', '').strip()
        
        result = {'username_available': True, 'email_available': True}
        
        if username:
            existing_user = User.by_user_name(username)
            result['username_available'] = existing_user is None
            
        if email:
            existing_user = User.by_email_address(email)
            result['email_available'] = existing_user is None
            
        return result

    @expose()
    def register_redirect(self, **kw):
        """
        Registration endpoint that redirects to login with flash message
        This provides a fallback for non-AJAX registration
        """
        try:
            # Extract required fields
            email = kw.get('email', '').strip()
            username = kw.get('username', '').strip()
            fullname = kw.get('fullname', '').strip()
            password = kw.get('password', '').strip()
            research_area = kw.get('research_area', '').strip()
            institution_affiliation = kw.get('institution_affiliation', '').strip()
            funding_agency = kw.get('funding_agency', '').strip()

            # Validation
            if not email or not username or not fullname or not password:
                flash('Missing required fields: email, username, fullname, and password are required', 'error')
                redirect('/registration/')

            if not research_area or not institution_affiliation:
                flash('Research area and institution affiliation are required', 'error')
                redirect('/registration/')

            if len(password) < 6:
                flash('Password must be at least 6 characters long', 'error')
                redirect('/registration/')

            # Check for existing users
            existing_user_email = User.by_email_address(email)
            if existing_user_email:
                flash('A user with this email address already exists', 'error')
                redirect('/registration/')

            existing_user_name = User.by_user_name(username)
            if existing_user_name:
                flash('This username is already taken', 'error')
                redirect('/registration/')

            # Validate research area options
            valid_research_areas = [
                'Bioinformatics', 'Cell Biology', 'Developmental Biology', 'Ecology', 
                'Genetics', 'Immunology', 'Materials Science', 'Microbiology', 
                'Molecular Biology', 'Neuroscience', 'Pharmacology', 'Plant Biology', 
                'Structural Biology', 'Other'
            ]
            if research_area and research_area not in valid_research_areas:
                flash(f'Invalid research area. Must be one of: {", ".join(valid_research_areas)}', 'error')
                redirect('/registration/')

            # Create user using the same logic as the JSON endpoint
            log.info(f"Creating new user: {username} ({email})")

            # Create the core TurboGears User first
            tg_user = User(
                user_name=username,
                email_address=email,
                display_name=fullname,
                password=password
            )
            DBSession.add(tg_user)
            DBSession.flush()  # Get the TG user ID, this also triggers bquser_callback
            
            # The bquser_callback automatically creates a BQUser, so let's find it
            from bq.data_service.model import BQUser
            bq_user = DBSession.query(BQUser).filter_by(resource_name=username).first()
            if not bq_user:
                # Fallback: create BQUser manually if callback didn't work
                bq_user = BQUser(tg_user=tg_user, create_tg=False, create_store=True)
                DBSession.add(bq_user)
                DBSession.flush()
                bq_user.owner_id = bq_user.id
            
            # Add custom tags for the extended profile information
            from bq.data_service.model.tag_model import Tag
            
            # Create all tags
            fullname_tag = Tag(parent=bq_user)
            fullname_tag.name = 'fullname'
            fullname_tag.value = fullname
            DBSession.add(fullname_tag)
            
            username_tag = Tag(parent=bq_user)
            username_tag.name = 'username'
            username_tag.value = username
            DBSession.add(username_tag)
            
            research_area_tag = Tag(parent=bq_user)
            research_area_tag.name = 'research_area'
            research_area_tag.value = research_area
            DBSession.add(research_area_tag)
            
            institution_tag = Tag(parent=bq_user)
            institution_tag.name = 'institution_affiliation'
            institution_tag.value = institution_affiliation
            DBSession.add(institution_tag)
            
            # Add funding agency tag (if provided)
            if funding_agency:
                funding_tag = Tag(parent=bq_user)
                funding_tag.name = 'funding_agency'
                funding_tag.value = funding_agency
                DBSession.add(funding_tag)
            
            log.info(f"Successfully created user: {username} with ID: {bq_user.resource_uniq}")
            
            # Handle email verification
            email_verification_status = self._safe_email_call('validate_configuration')
            email_verification_available = email_verification_status.get('available', False) if email_verification_status else False

            if email_verification_available:
                log.info(f"Email verification is available - sending verification email to {email}")
                
                # Generate verification token
                verification_token = self._safe_email_call('generate_verification_token', email, username)
                
                # Get base URL for verification link  
                base_url = request.host_url.rstrip('/')
                
                # Send verification email
                send_result = self._safe_email_call('send_verification_email', 
                    email, username, fullname, verification_token, base_url)
                if send_result and send_result.get('success'):
                    log.info(f"Verification email sent successfully to {email}")
                    
                    # Store verification token as a tag for later verification
                    token_tag = Tag(parent=bq_user)
                    token_tag.name = 'email_verification_token'
                    token_tag.value = verification_token
                    token_tag.owner = bq_user
                    DBSession.add(token_tag)
                    
                    flash(f'Account created successfully for {fullname}! Please check your email ({email}) for a verification link before signing in.', 'success')
                else:
                    log.error(f"Failed to send verification email to {email}: {send_result}")
                    # Mark user as verified if email sending fails
                    self._safe_email_call('mark_user_as_verified', bq_user)
                    flash(f'Account created successfully for {fullname}! Email verification failed, but you can sign in immediately.', 'warning')
            else:
                log.info(f"Email verification not available - marking user as verified automatically")
                # Mark user as verified when email verification is not available
                self._safe_email_call('mark_user_as_verified', bq_user)
                flash(f'Account created successfully for {fullname}! Please sign in with your new credentials.', 'success')
            
            redirect('/client_service/')

        except Exception as e:
            # Let TurboGears transaction manager handle rollback
            log.error(f"Registration failed for {kw.get('email', 'unknown')}: {str(e)}")
            import traceback
            log.error(f"Full traceback: {traceback.format_exc()}")
            flash('Registration failed due to server error. Please try again.', 'error')
            redirect('/registration/')

    @expose()
    def register_with_redirect(self, **kw):
        """
        Alternative registration endpoint that uses TurboGears flash messages and redirect
        This is used as a fallback when JavaScript is disabled
        """
        try:
            # Extract required fields for validation (same as JSON endpoint)
            email = kw.get('email', '').strip()
            username = kw.get('username', '').strip()
            fullname = kw.get('fullname', '').strip()
            password = kw.get('password', '').strip()
            research_area = kw.get('research_area', '').strip()
            institution_affiliation = kw.get('institution_affiliation', '').strip()
            funding_agency = kw.get('funding_agency', '').strip()

            # Validation (same logic as JSON endpoint but with redirects)
            if not email or not username or not fullname or not password:
                flash('Missing required fields: email, username, fullname, and password are required', 'error')
                redirect('/registration/')

            if not research_area or not institution_affiliation:
                flash('Research area and institution affiliation are required', 'error')
                redirect('/registration/')

            if len(password) < 6:
                flash('Password must be at least 6 characters long', 'error')
                redirect('/registration/')

            # Check for existing users
            existing_user_email = User.by_email_address(email)
            if existing_user_email:
                flash('A user with this email address already exists', 'error')
                redirect('/registration/')

            existing_user_name = User.by_user_name(username)
            if existing_user_name:
                flash('This username is already taken', 'error')
                redirect('/registration/')

            # Validate research area options
            valid_research_areas = [
                'Bioinformatics', 'Cell Biology', 'Developmental Biology', 'Ecology', 
                'Genetics', 'Immunology', 'Materials Science', 'Microbiology', 
                'Molecular Biology', 'Neuroscience', 'Pharmacology', 'Plant Biology', 
                'Structural Biology', 'Other'
            ]
            if research_area and research_area not in valid_research_areas:
                flash(f'Invalid research area. Must be one of: {", ".join(valid_research_areas)}', 'error')
                redirect('/registration/')

            # Create user using the same logic as the JSON endpoint
            log.info(f"Creating new user: {username} ({email})")

            # Create the core TurboGears User first
            tg_user = User(
                user_name=username,
                email_address=email,
                display_name=fullname,
                password=password
            )
            DBSession.add(tg_user)
            DBSession.flush()  # Get the TG user ID, this also triggers bquser_callback
            
            # The bquser_callback automatically creates a BQUser, so let's find it
            from bq.data_service.model import BQUser
            bq_user = DBSession.query(BQUser).filter_by(resource_name=username).first()
            if not bq_user:
                # Fallback: create BQUser manually if callback didn't work
                bq_user = BQUser(tg_user=tg_user, create_tg=False, create_store=True)
                DBSession.add(bq_user)
                DBSession.flush()
                bq_user.owner_id = bq_user.id
            
            # Add custom tags for the extended profile information
            from bq.data_service.model.tag_model import Tag
            
            # Create all tags
            fullname_tag = Tag(parent=bq_user)
            fullname_tag.name = 'fullname'
            fullname_tag.value = fullname
            DBSession.add(fullname_tag)
            
            username_tag = Tag(parent=bq_user)
            username_tag.name = 'username'
            username_tag.value = username
            DBSession.add(username_tag)
            
            research_area_tag = Tag(parent=bq_user)
            research_area_tag.name = 'research_area'
            research_area_tag.value = research_area
            DBSession.add(research_area_tag)
            
            institution_tag = Tag(parent=bq_user)
            institution_tag.name = 'institution_affiliation'
            institution_tag.value = institution_affiliation
            DBSession.add(institution_tag)
            
            # Add funding agency tag (if provided)
            if funding_agency:
                funding_tag = Tag(parent=bq_user)
                funding_tag.name = 'funding_agency'
                funding_tag.value = funding_agency
                DBSession.add(funding_tag)
            
            log.info(f"Successfully created user: {username} with ID: {bq_user.resource_uniq}")
            
            # Handle email verification
            email_verification_status = self._safe_email_call('validate_configuration')
            email_verification_available = email_verification_status.get('available', False) if email_verification_status else False

            if email_verification_available:
                log.info(f"Email verification is available - sending verification email to {email}")
                
                # Generate verification token
                verification_token = self._safe_email_call('generate_verification_token', email, username)
                
                # Get base URL for verification link  
                base_url = request.host_url.rstrip('/')
                
                # Send verification email
                send_result = self._safe_email_call('send_verification_email', 
                    email, username, fullname, verification_token, base_url)
                if send_result and send_result.get('success'):
                    log.info(f"Verification email sent successfully to {email}")
                    
                    # Store verification token as a tag for later verification
                    token_tag = Tag(parent=bq_user)
                    token_tag.name = 'email_verification_token'
                    token_tag.value = verification_token
                    token_tag.owner = bq_user
                    DBSession.add(token_tag)
                    
                    flash(f'Account created successfully! Please check your email ({email}) for a verification link before signing in.', 'success')
                else:
                    log.error(f"Failed to send verification email to {email}: {send_result}")
                    # Mark user as verified if email sending fails
                    self._safe_email_call('mark_user_as_verified', bq_user)
                    flash('Account created successfully! Email verification failed, but you can sign in immediately.', 'warning')
            else:
                log.info(f"Email verification not available - marking user as verified automatically")
                # Mark user as verified when email verification is not available
                self._safe_email_call('mark_user_as_verified', bq_user)
                flash('Account created successfully! Please sign in with your new account.', 'success')
            
            redirect('/client_service/')
                
        except HTTPFound:
            # This is a normal TurboGears redirect - let it propagate
            raise
        except Exception as e:
            log.error(f"Registration with redirect failed: {str(e)}")
            import traceback
            log.error(f"Full traceback: {traceback.format_exc()}")
            flash('Registration failed due to server error. Please try again.', 'error')
            redirect('/registration/')

    @expose('bq.registration.templates.verify_email')
    def verify_email(self, **kw):
        """Email verification endpoint"""
        token = kw.get('token', '').strip()
        email = kw.get('email', '').strip()
        
        if not token or not email:
            flash('Invalid verification link. Please check your email for the correct link.', 'error')
            redirect('/registration/')
        
        try:
            # Find user by email
            from bq.data_service.model import BQUser
            bq_user = None
            
            # Search for user by email (stored in the value field)
            users = DBSession.query(BQUser).filter(BQUser.resource_value == email).all()
            if not users:
                flash('User not found. Please register again.', 'error')
                redirect('/registration/')
            
            bq_user = users[0]
            username = bq_user.resource_name
            
            # Check if user is already verified
            if self._safe_email_call("is_user_verified", bq_user):
                flash('Your email is already verified! You can sign in normally.', 'success')
                redirect('/client_service/')
            
            # Get stored verification token
            from bq.data_service.model.tag_model import Tag
            token_tag = DBSession.query(Tag).filter(
                Tag.parent == bq_user,
                Tag.name == 'email_verification_token'
            ).first()
            
            if not token_tag:
                flash('Verification token not found. Please request a new verification email.', 'error')
                redirect('/registration/resend_verification')
            
            # Verify the token
            if not self._safe_email_call("verify_token", token, email, username):
                flash('Invalid or expired verification link. Please request a new verification email.', 'error')
                redirect('/registration/resend_verification')
            
            # Mark user as verified
            if self._safe_email_call("mark_user_as_verified", bq_user):
                # Remove the verification token
                DBSession.delete(token_tag)
                DBSession.flush()
                
                flash(f'Email verified successfully! Welcome to Bisque, {bq_user.get("display_name", username)}. You can now sign in.', 'success')
                redirect('/client_service/')
            else:
                flash('Verification failed due to a server error. Please try again.', 'error')
                redirect('/registration/')
            
        except Exception as e:
            log.error(f"Email verification failed: {e}")
            flash('Verification failed due to a server error. Please try again.', 'error')
            redirect('/registration/')
    
    @expose('bq.registration.templates.resend_verification')
    def resend_verification(self, **kw):
        """Resend verification email page"""
        if not self._safe_email_call("is_available", ):
            flash('Email verification is not available.', 'error')
            redirect('/registration/')
        
        return {'msg': 'Resend verification email'}
    
    @expose('json')
    def send_verification(self, **kw):
        """Send verification email endpoint"""
        if not self._safe_email_call("is_available", ):
            return {'status': 'error', 'message': 'Email verification is not available'}
        
        email = kw.get('email', '').strip()
        if not email:
            return {'status': 'error', 'message': 'Email address is required'}
        
        try:
            # Find user by email
            from bq.data_service.model import BQUser
            users = DBSession.query(BQUser).filter(BQUser.resource_value == email).all()
            if not users:
                return {'status': 'error', 'message': 'User not found with this email address'}
            
            bq_user = users[0]
            username = bq_user.resource_name
            
            # Check if already verified
            if self._safe_email_call("is_user_verified", bq_user):
                return {'status': 'success', 'message': 'Your email is already verified! You can sign in normally.'}
            
            # Get user's full name
            from bq.data_service.model.tag_model import Tag
            fullname_tag = DBSession.query(Tag).filter(
                Tag.parent == bq_user,
                Tag.name == 'fullname'
            ).first()
            fullname = fullname_tag.value if fullname_tag else username
            
            # Generate new verification token
            verification_token = self._safe_email_call("generate_verification_token", email, username)
            
            # Update verification token
            token_tag = DBSession.query(Tag).filter(
                Tag.parent == bq_user,
                Tag.name == 'email_verification_token'
            ).first()
            
            if token_tag:
                token_tag.value = verification_token
            else:
                token_tag = Tag(parent=bq_user)
                token_tag.name = 'email_verification_token'
                token_tag.value = verification_token
                token_tag.owner = bq_user
                DBSession.add(token_tag)
            
            # Send verification email
            base_url = request.host_url.rstrip('/')
            self._safe_email_call("send_verification_email",
                email, username, fullname, verification_token, base_url
            )
            
            return {'status': 'success', 'message': 'Verification email sent successfully! Please check your email.'}
            
        except EmailVerificationError as e:
            log.error(f"Failed to resend verification email: {e}")
            return {'status': 'error', 'message': f'Failed to send verification email: {e}'}
        except Exception as e:
            log.error(f"Resend verification failed: {e}")
            return {'status': 'error', 'message': 'Failed to send verification email due to server error'}
    
    @expose('bq.registration.templates.verify_email')
    def verify(self, token=None, **kw):
        """Email verification endpoint with token in URL path: /registration/verify/{token}"""
        if not token:
            flash('Invalid verification link. Missing verification token.', 'error')
            redirect('/registration/')
        
        token = token.strip()
        
        try:
            # Find the user by searching for the verification token
            from bq.data_service.model import BQUser
            from bq.data_service.model.tag_model import Tag
            
            # Find user by verification token
            token_tag = DBSession.query(Tag).filter(
                Tag.name == 'email_verification_token',
                Tag.value == token
            ).first()
            
            if not token_tag:
                flash('Invalid or expired verification link. Please request a new verification email.', 'error')
                redirect('/registration/resend_verification')
            
            bq_user = token_tag.parent
            if not bq_user:
                flash('User not found. Please register again.', 'error')
                redirect('/registration/')
            
            username = bq_user.resource_name
            email = bq_user.resource_value
            
            # Check if user is already verified
            if self._safe_email_call("is_user_verified", bq_user):
                flash('Your email is already verified! You can sign in normally.', 'success')
                redirect('/client_service/')
            
            # Verify the token
            if not self._safe_email_call("verify_token", token, email, username):
                flash('Invalid or expired verification link. Please request a new verification email.', 'error')
                redirect('/registration/resend_verification')
            
            # Mark user as verified
            verify_result = self._safe_email_call("mark_user_as_verified", bq_user)
            if verify_result and verify_result.get('success'):
                # Remove the verification token
                DBSession.delete(token_tag)
                DBSession.flush()
                
                display_name = bq_user.get("display_name", username)
                flash(f'Email verified successfully! Welcome to Bisque, {display_name}. You can now sign in.', 'success')
                redirect('/client_service/')
            else:
                error_msg = verify_result.get('error', 'Unknown error') if verify_result else 'Unknown error'
                flash(f'Verification failed: {error_msg}. Please try again.', 'error')
                redirect('/registration/')
            
        except Exception as e:
            log.error(f"Email verification failed: {e}")
            import traceback
            log.error(f"Full traceback: {traceback.format_exc()}")
            flash('Verification failed due to a server error. Please try again.', 'error')
            redirect('/registration/')