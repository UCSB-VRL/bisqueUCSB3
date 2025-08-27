"""Simplified authenticator plugin for BisQue"""
from repoze.who.plugins.sql import (
    SQLAuthenticatorPlugin,
    SQLMetadataProviderPlugin,
    make_authenticator_plugin,
    make_metadata_plugin
)

def auth_plugin(**kwargs):
    """Create a simple authenticator plugin that always passes authentication"""
    class SimpleAuthPlugin:
        def authenticate(self, environ, identity):
            # Simple authentication that accepts admin/admin
            login = identity.get('login')
            password = identity.get('password')
            if login == 'admin' and password == 'admin':
                return login
            return None
    return SimpleAuthPlugin()

def md_plugin(**kwargs):
    """Create a simple metadata provider plugin"""
    class SimpleMdPlugin:
        def add_metadata(self, environ, identity):
            # Add basic metadata for authenticated users
            if identity.get('repoze.who.userid'):
                identity['user'] = identity['repoze.who.userid']
    return SimpleMdPlugin()

def md_group_plugin(**kwargs):
    """Create a simple group metadata provider plugin"""
    class SimpleGroupPlugin:
        def add_metadata(self, environ, identity):
            # Add basic group info for authenticated users
            if identity.get('repoze.who.userid'):
                identity['groups'] = ['users']  # Default group
    return SimpleGroupPlugin()
