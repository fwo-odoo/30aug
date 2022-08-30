# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import fields, models, api

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        base_edi = self.env['edi.sync.action']
        for order in self:
            if order.partner_id.x_outbound_edi_poa:
                sync_action = base_edi.search([('doc_type_id.doc_code', '=', 'export_sale_acknowledgement_xml')])
                if sync_action:
                    base_edi._do_doc_sync_cron(sync_action_id=sync_action, records=self)
        return res

