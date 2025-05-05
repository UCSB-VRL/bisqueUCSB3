import logging
from tg import expose, validate, request
from bq.core.lib.base import BaseController

log = logging.getLogger("bq.registration")

class RegistrationController(BaseController):
    """
    !!! Minimal replacement for tgext.registration2 UserRegistration
    """

    service_type = "registration"

    @expose('json')
    def index(self, **kw):
        return {'status': 'ok', 'message': 'Registration service is running.'}

    @expose('json')
    def register(self, **kw):
        email = kw.get('email')
        password = kw.get('password')

        if not email or not password:
            return {'status': 'error', 'message': 'Missing email or password'}

        # Here you would create a new user in the database
        log.info(f"Registering new user: {email}")

        # Example of saving user (you can customize this logic)
        from bq.data_service.model import BQUser
        new_user = BQUser.new_user(email, password)
        
        return {'status': 'success', 'user_id': new_user.resource_uniq}

    @expose('json')
    def confirm(self, **kw):
        code = kw.get('code')
        # Confirm user registration based on code if you implement that
        return {'status': 'success', 'message': 'User confirmed (not really implemented).'}
