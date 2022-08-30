# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import logging
import requests
from werkzeug.exceptions import BadRequest

from odoo import api, http, SUPERUSER_ID, _
from odoo import registry as registry_get
from odoo.addons.web.controllers.main import db_monodb, ensure_db, set_cookie_and_redirect, login_and_redirect


_logger = logging.getLogger(__name__)


class SPSAuthController(http.Controller):

    @http.route('/edi_sps/espso', type='http', auth='none')
    def espso(self, **kw):
        '''
        SPS Commerce auth code/token callback
        '''
        url = '/web'
        code = kw.get('code')
        state = kw.get('state')
        if code and state:
            try:
                decoded_code = base64.b64decode(state).decode('utf-8')
                code_segments = decoded_code.split(';')
            except Exception as ex:
                _logger.exception("edi_sps: %s" % str(ex))
                return BadRequest()
            if len(code_segments) != 4:
                _logger.exception("edi_sps: received invalid code %s" %(decoded_code))
                return BadRequest()
            if not http.db_filter([code_segments[0]]):
                return BadRequest()
            registry = registry_get(code_segments[0])
            with registry.cursor() as cr:
                env = api.Environment(cr, int(code_segments[1]), {})
                auth_requests = env[code_segments[2].split(',')[0]].search([('auth_request_state', '=', decoded_code)])
                if auth_requests:
                    for auth_req in auth_requests:
                        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
                        spe_token_url = 'https://auth.spscommerce.com/oauth/token'
                        datas = {
                          'grant_type': 'authorization_code',
                          'client_id': auth_req.app_clientid,
                          'client_secret': auth_req.app_secret,
                          'code': code,
                          'redirect_uri': base_url,
                        }
                        try:
                            vals = {
                                'app_auth_state': 'auth',
                                'token_request_error': '',
                            }
                            resp = requests.post(spe_token_url, data=datas)
                            resp_json = resp.json()
                            if 'error' in resp_json:
                                vals.update({
                                    'app_auth_state': 'error',
                                    'token_request_error': '%s. %s'%(resp_json.get('error'). resp_json.get('error_description', '')),
                                })
                            else:
                                vals.update({
                                    'access_token': resp_json.get('access_token'),
                                    'refresh_token': resp_json.get('refresh_token'),
                                    'token_expire_in': int(resp_json.get('expires_in')) / 3600,
                                    'refresh_token': resp_json.get('refresh_token'),
                                    'auth_request_state': False,
                                })
                            auth_requests.sudo().write(vals)
                            action = env.ref('base_edi.action_edi_config_form')
                            url = '/web#action=%s' % action.id
                        except Exception as ex:
                            _logger.exception("edi_sps: token request failed with state values : %s" %(decoded_code))
                            _logger.exception("edi_sps: %s" %(ex))
                            auth_req.sudo().write({
                                'app_auth_state': 'error',
                                'token_request_error': 'Token request failed.'
                            })
                        env.cr.commit()
        return set_cookie_and_redirect(url)
