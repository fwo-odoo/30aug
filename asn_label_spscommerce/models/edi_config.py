# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import uuid
import base64
import pprint
import logging
import urllib.parse
import requests

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)
EDI_DATE_FORMAT = '%Y-%m-%d'

class EDIConfig(models.Model):

    _inherit = 'edi.config'

    app_clientid = fields.Char(string='SPSCommerce App ClientId')
    app_secret = fields.Char(string='SPSCommerce App Secret')
    auth_request_state = fields.Char(string='Auth Request State Token', readonly=True)
    access_token = fields.Text(string='Access Token', readonly=True)
    refresh_token = fields.Char(string='Refresh Token', readonly=True)
    token_expire_in = fields.Integer(string='Expire In (Seconds)', readonly=True,
                            help='Time to access token expiration in hours')
    token_request_error = fields.Char(string='Token Request Error')
    app_auth_state = fields.Selection(selection=[
                                ('null', 'Not Required'),
                                ('request', 'Required'),
                                ('sent', 'Request Sent'),
                                ('error', 'Error'),
                                ('auth', 'Authorized'),
                                ('expire', 'Expired')
                            ], string='Authentication State')


    def renew_access_token(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        spe_token_url = 'https://auth.spscommerce.com/oauth/token'
        configs = self

        # self will be empty when this method is called by a cron
        if not configs:
            configs = self.env['edi.config'].search([('app_clientid', '!=', False)])

        for config in configs:
            if not config.app_clientid or not config.app_secret or not config.refresh_token:
                raise ValidationError('Missing fields required to resfresh authentication of ASN Label API')

            datas = {
              'grant_type': 'refresh_token',
              'client_id': config.app_clientid,
              'client_secret': config.app_secret,
              'refresh_token': config.refresh_token,
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
                        'token_expire_in': int(resp_json.get('expires_in')) / 3600,
                        'auth_request_state': False,
                    })
                config.sudo().write(vals)
                action = config.env.ref('base_edi.action_edi_config_form')
                url = '/web#action=%s' % action.id
            except Exception as ex:
                _logger.exception("edi_sps: Refresh Token failed")
                _logger.exception("edi_sps: %s" %(ex))
                config.sudo().write({
                    'app_auth_state': 'error',
                    'token_request_error': 'Token request failed.'
                })
            config.env.cr.commit()

    def authenticate_client_id(self):
        self.ensure_one()
        sps_url = 'https://auth.spscommerce.com/authorize?%s'
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        ret_url = urllib.parse.urljoin(base_url, '/edi_sps/espso')
        auth_request_state = '%s;%d;%s;%s'%(
                self._cr.dbname,
                self.env.uid,
                '%s,%d'%(self._name, self.id),
                str(uuid.uuid4())
        )
        auth_request_state = auth_request_state.encode(encoding='UTF-8')
        params = {
            'audience': 'api://api.spscommerce.com/',
            'scope': 'offline_access',
            'response_type': 'code',
            'client_id': self.app_clientid,
            'redirect_uri': ret_url,
            'state': base64.b64encode(auth_request_state),
        }
        encoded_url = urllib.parse.urlencode(params)
        final_url = sps_url%encoded_url
        self.write({
            'app_auth_state': 'sent',
            'auth_request_state': auth_request_state,
            'token_request_error': False,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': final_url,
            'target': 'new',
            'target_type': 'public',
            'res_id': self.id,
        }