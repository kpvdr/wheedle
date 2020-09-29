"""
Error classes used by the poller.
"""

class PollerError(RuntimeError):
    """ Parent class for all poller errors """



class ContentTypeError(PollerError):
    """ Error when the returned information is not of type application/json """
    def __init__(self, response):
        super().__init__('ContentTypeError: GET {} returned unexpected content-type {}'.format( \
            response.url[0: response.url.find('?')],
            response.headers['content-type']))
        self.response = response



class DisabledRepoError(PollerError):
    """ Error when the GH project is disabled """
    def __init__(self, repo_full_name):
        super().__init__('DisabledRepoError: Repository {} is disabled'.format(repo_full_name))



class ErrorList(PollerError):
    """ Allows multiple exception objects to be raised together """
    def __init__(self, error_list):
        self._error_list = error_list
        err_msg = ''
        if len(error_list) > 0:
            first = True
            for error in error_list:
                if not first:
                    err_msg += '\n'
                err_msg += str(error)
                first = False
        else:
            err_msg = '[]'
        super().__init__(err_msg)
    def contains_class(self, clazz):
        """ Return True if list contains class clazz """
        for err in self._error_list:
            if isinstance(err, clazz):
                return True
        return False
    def __iter__(self):
        return self._error_list.__iter__()



class HttpError(PollerError):
    """ Error when a HTTP GET request returns anything other than 200 (ok) """
    def __init__(self, response):
        super().__init__('HttpError: GET {} returned status {} ({})'.format( \
            response.url[0: response.url.find('?')], response.status_code, response.reason))
        self.response = response



class ServiceConnectionError(PollerError):
    """ Error when the connection to a service fails """
    def __init__(self, service_name, service_url):
        super().__init__('ServiceConnectionError: {0} not running or invalid {0} URL {1}'.format( \
            service_name, service_url))



class TokenNotFoundError(PollerError):
    """ Error if GitHub token not found """
    def __init__(self, token_file_name):
        super().__init__('TokenNotFoundError: GitHub token file not found at {}'.format( \
            token_file_name))
