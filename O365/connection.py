import logging
import os
import os.path as path
import json

import requests
from oauthlib.oauth2 import TokenExpiredError
from requests_oauthlib import OAuth2Session
from future.utils import with_metaclass


log = logging.getLogger(__name__)


class MicroDict(dict):
	def __getitem__(self, key):
		result = super(MicroDict, self).get(key[:1].lower() + key[1:], None)
		if result is None:
			result = super(MicroDict, self).get(key[:1].upper() + key[1:])
		return result


class Singleton(type):
	_instance = None

	def __call__(cls, *args, **kwargs):
		if not cls._instance:
			cls._instance = super(Singleton, cls).__call__(*args, **kwargs)
		return cls._instance

	# def __new__(cls, *args, **kwargs):
	#	 if not cls._instance:
	#		 cls._instance = object.__new__(cls)
	#	 return cls._instance


_default_token_file = '.o365_token'
_home_path = path.expanduser("~")
default_token_path = path.join(_home_path, _default_token_file)


def save_token(token, token_path=None):
	""" Save the specified token dictionary to a specified file path

	:param token: token dictionary returned by the oauth token request
	:param token_path: path to where the files is to be saved
	"""
	if not token_path:
		token_path = default_token_path

	with open(token_path, 'w') as token_file:
		json.dump(token, token_file, indent=True)


def load_token(token_path=None):
	""" Save the specified token dictionary to a specified file path

	:param token_path: path to the file with token information saved
	"""
	if not token_path:
		token_path = default_token_path

	token = None
	if path.exists(token_path):
		with open(token_path, 'r') as token_file:
			token = json.load(token_file)
	return token


def delete_token(token_path=None):
	""" Save the specified token dictionary to a specified file path

	:param token_path: path to where the token is saved
	"""
	if not token_path:
		token_path = default_token_path

	if path.exists(token_path):
		os.unlink(token_path)


class Connection(with_metaclass(Singleton)):
	_oauth2_authorize_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
	_oauth2_token_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'

	def __init__(self):
		""" Creates a O365 connection object """
		self.api_version = None
		self.auth = None

		self.oauth = None
		self.client_id = None
		self.client_secret = None
		self.token = None

		self.proxy_dict = None

	def is_valid(self):
		valid = False

		if self.api_version == '1.0':
			valid = True if self.auth else False
		elif self.api_version == '2.0':
			valid = True if self.oauth else False

		return valid

	@staticmethod
	def login(username, password):
		""" Connect to office 365 using specified username and password

		:param username: username to login with
		:param password: password for authentication
		"""
		connection = Connection()

		connection.api_version = '1.0'
		connection.auth = (username, password)
		return connection

	@staticmethod
	def oauth2(client_id, client_secret, store_token=True, token_path=None):
		""" Connect to office 365 using specified Open Authentication protocol

		:param client_id: application_id generated by https://apps.dev.microsoft.com when you register your app
		:param client_secret: secret password key generated for your application
		:param store_token: whether or not to store the token in file system, so u don't have to keep opening
			the auth link and authenticating every time
		:param token_path: full path to where the token should be saved to
		"""
		connection = Connection()

		connection.api_version = '2.0'
		connection.client_id = client_id
		connection.client_secret = client_secret

		if not store_token:
			delete_token(token_path)

		token = load_token(token_path)

		if not token:
			connection.oauth = OAuth2Session(client_id=client_id,
											 redirect_uri='https://outlook.office365.com/owa/',
											 scope=['https://graph.microsoft.com/Mail.ReadWrite',
													'https://graph.microsoft.com/Mail.Send',
													'offline_access'], )
			oauth = connection.oauth
			auth_url, state = oauth.authorization_url(
				url=Connection._oauth2_authorize_url,
				access_type='offline')
			print('Please open {} and authorize the application'.format(auth_url))
			auth_resp = input('Enter the full result url: ')
			os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = 'Y'
			token = oauth.fetch_token(token_url=Connection._oauth2_token_url,
									  authorization_response=auth_resp, client_secret=client_secret)
			save_token(token, token_path)
		else:
			connection.oauth = OAuth2Session(client_id=client_id,
											 token=token)

		return connection

	@staticmethod
	def proxy(url, port, username, password):
		""" Connect to Office 365 though the specified proxy

		:param url: url of the proxy server
		:param port: port to connect to proxy server
		:param username: username for authentication in the proxy server
		:param password: password for the specified username
		"""
		connection = Connection()

		connection.proxy_dict = {
			"http": "http://{}:{}@{}:{}".format(username, password, url, port),
			"https": "https://{}:{}@{}:{}".format(username, password, url,
												  port),
		}
		return connection

	@staticmethod
	def get_response(request_url, **kwargs):
		""" Fetches the response for specified url and arguments, adding the auth and proxy information to the url

		:param request_url: url to request
		:param kwargs: any keyword arguments to pass to the requests api
		:return: response object
		"""
		connection = Connection()

		if not connection.is_valid():
			raise RuntimeError('Connection is not configured, please use "O365.Connection" '
							   'to set username and password or OAuth2 authentication')

		con_params = {}
		if connection.proxy_dict:
			con_params['proxies'] = connection.proxy_dict
		con_params.update(kwargs)

		log.info('Requesting URL: {}'.format(request_url))

		if connection.api_version == '1.0':
			con_params['auth'] = connection.auth
			response = requests.get(request_url, **con_params)
		else:
			try:
				response = connection.oauth.get(request_url, **con_params)
			except TokenExpiredError:
				log.info('Token is expired, fetching a new token')
				token = connection.oauth.refresh_token(Connection._oauth2_token_url, client_id=connection.client_id,
													   client_secret=connection.client_secret)
				log.info('New token fetched')
				save_token(token)

				response = connection.oauth.get(request_url, **con_params)

		log.info('Received response from URL {}'.format(response.url))

		response_json = response.json()
		if 'value' not in response_json:
			raise RuntimeError('Something went wrong, received an unexpected result \n{}'.format(response_json))

		response_values = [MicroDict(x) for x in response_json['value']]
		return response_values
