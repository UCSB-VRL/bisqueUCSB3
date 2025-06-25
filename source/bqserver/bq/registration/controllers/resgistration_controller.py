import logging
from tg import expose, validate, request, redirect, flash
from tg.exceptions import HTTPFound
from bq.core.lib.base import BaseController
from bq.core.model import DBSession
from bq.core.model.auth import User

log = logging.getLogger("bq.registration")

class RegistrationController(BaseController):
    """
    Enhanced registration controller for Bisque user registration
    Supports: email, username, fullname, research area, institution, funding agency
    """

    service_type = "registration"

    @expose('bq.registration.templates.index')
    def index(self, **kw):
        """Registration form page"""
        return {'msg': 'Welcome to user registration'}

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
            
            return {
                'status': 'success', 
                'message': 'Account created successfully',
                'user_id': bq_user.resource_uniq,
                'username': username
            }

        except Exception as e:
            # Let TurboGears transaction manager handle rollback
            log.error(f"Registration failed for {kw.get('email', 'unknown')}: {str(e)}")
            import traceback
            log.error(f"Full traceback: {traceback.format_exc()}")
            return {'status': 'error', 'message': 'Registration failed due to server error. Please try again.'}

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
            
            # Set success flash message and redirect to login
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
            
            # Success - redirect to login with success message
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