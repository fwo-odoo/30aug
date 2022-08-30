# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import os
import pprint
import pytz

from datetime import datetime, date, timedelta
from lxml import etree as ET  # DOC : https://lxml.de/api/index.html
from math import ceil

from odoo import api, fields, models, _

EDI_DATE_FORMAT = '%Y-%m-%d'

_logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)

ns = {'sps': 'http://www.spscommerce.com/RSX'}


class SyncDocumentType(models.Model):
    _inherit = 'sync.document.type'

    doc_code = fields.Selection(selection_add=[
        ('export_sale_acknowledgement_xml', '855 - Export Sale Acknowledgement')
    ], ondelete={'export_sale_acknowledgement_xml': 'cascade'})


    def make_saleorder_line_xml_data(self, order, order_root):
        line_count = 0

        for line in order.order_line:
            if not line.display_type:
                line_item = ET.Element('LineItem')

                order_line = ET.SubElement(line_item, 'OrderLine')
                ET.SubElement(order_line, 'LineSequenceNumber').text = str(line.x_line_sequence_number) or 1
                ET.SubElement(order_line, 'BuyerPartNumber').text = line.x_buyer_part_number or ''
                ET.SubElement(order_line, 'VendorPartNumber').text = line.x_vendor_part_number or ''
                ET.SubElement(order_line, 'ConsumerPackageCode').text = line.x_consumer_package_code or line.product_id.barcode or ''
                ET.SubElement(order_line, 'EAN').text = line.product_id.x_ean or ''
                ET.SubElement(order_line, 'GTIN').text = line.product_id.x_gtin or ''
                product_id_block = ET.SubElement(order_line, 'ProductID')
                ET.SubElement(product_id_block, 'PartNumber').text = line.x_part_number or ''
                ET.SubElement(order_line, 'OrderQty').text = str(float(ceil(line.x_qty_cases))) if line.product_uom.x_edi_code in ['CA', 'PL'] else str(line.product_uom_qty) or '1'
                ET.SubElement(order_line, 'OrderQtyUOM').text = line.product_uom.x_edi_code or 'EA'
                price = line.x_case_price if order.partner_id.x_price_in_cases else line.price_unit
                ET.SubElement(order_line, 'PurchasePrice').text = str(round(price, 2)) or '0'

                line_item_acknoledgement = ET.SubElement(line_item, 'LineItemAcknowledgement')
                ET.SubElement(line_item_acknoledgement, 'ItemStatusCode').text = line.x_item_status_code or 'IB'
                ET.SubElement(line_item_acknoledgement, 'ItemScheduleQty').text =  str(float(ceil(line.x_qty_cases))) if line.product_uom.x_edi_code in ['CA', 'PL'] else str(line.product_uom_qty) or '1'
                ET.SubElement(line_item_acknoledgement, 'ItemScheduleUOM').text = line.product_uom.x_edi_code or 'EA'
                ET.SubElement(line_item_acknoledgement, 'ItemScheduleQualifier').text = '068'
                date = order.commitment_date or order.x_requested_pickup_date or order.x_additional_date or fields.Datetime.now()
                ET.SubElement(line_item_acknoledgement, 'ItemScheduleDate').text = date.strftime(EDI_DATE_FORMAT) or 'Not provided'

                product_or_item_description = ET.SubElement(line_item, 'ProductOrItemDescription')
                ET.SubElement(product_or_item_description, 'ProductCharacteristicCode').text = '08'
                ET.SubElement(product_or_item_description, 'ProductDescription').text = line.name or line.product_id.description or line.product_id.description_sale or 'Item Description'

                physical_details = ET.SubElement(line_item, 'PhysicalDetails')
                ET.SubElement(physical_details, 'PackSize').text = str(line.product_packaging_id.qty) or ''

                line_count = line_count + 1
                order_root.append(line_item)

        return line_count


    def make_saleorder_xml_data(self, order):
        order_root = ET.Element('OrderAck')
        header = ET.SubElement(order_root, 'Header')

        # OrderHeader
        order_header = ET.SubElement(header, 'OrderHeader')
        partner = order.partner_id
        ET.SubElement(order_header, 'TradingPartnerId').text = partner.trading_partnerid or ''
        ET.SubElement(order_header, 'PurchaseOrderNumber').text = order.x_po_number or ''
        ET.SubElement(order_header, 'TsetPurposeCode').text = order.x_tset_purpose_code or ''
        ET.SubElement(order_header, 'PurchaseOrderDate').text = datetime.strftime(order.date_order, EDI_DATE_FORMAT)
        ET.SubElement(order_header, 'AcknowledgementNumber').text = order.name or ''
        ET.SubElement(order_header, 'AcknowledgementType').text = order.x_acknowledgement_type or 'AC'

        # Dates
        order_dates = ET.SubElement(header, 'Dates')
        ET.SubElement(order_dates, 'DateTimeQualifier').text = order.x_date_time_qualifier or ''

        if order.x_date_time_qualifier == '002':
            date = order.commitment_date
        elif order.x_date_time_qualifier == '118':
            date = order.x_requested_pickup_date
        else:
            date = order.x_additional_date
        if not date:
            date = fields.Datetime.now()
        ET.SubElement(order_dates, 'Date').text = datetime.strftime(date, EDI_DATE_FORMAT) or ''


        # Address of the location where the order is being shipped FROM
        address = ET.SubElement(header, 'Address')
        ET.SubElement(address, 'AddressTypeCode').text = 'SF'
        ET.SubElement(address, 'LocationCodeQualifier').text = order.company_id.partner_id.x_location_code_qualifier or '9'
        ET.SubElement(address, 'AddressLocationNumber').text = order.company_id.partner_id.x_address_location_number or ''
        ET.SubElement(address, 'AddressName').text = order.company_id.name or 'Address Name'
        ET.SubElement(address, 'Address1').text = order.company_id.street or ''
        ET.SubElement(address, 'Address2').text = order.company_id.street2 or ''
        ET.SubElement(address, 'City').text = order.company_id.city or ''
        ET.SubElement(address, 'State').text = order.company_id.state_id.code or ''
        ET.SubElement(address, 'PostalCode').text = order.company_id.zip or ''
        ET.SubElement(address, 'Country').text = order.company_id.country_id.code or ''

        # Address of the location where the order is being shipped TO
        if order.partner_shipping_id:
            address = ET.SubElement(header, 'Address')
            ET.SubElement(address, 'AddressTypeCode').text = 'ST'
            ET.SubElement(address, 'LocationCodeQualifier').text = order.partner_shipping_id.x_location_code_qualifier or '9'
            ET.SubElement(address, 'AddressLocationNumber').text = order.partner_shipping_id.x_address_location_number or ''
            ET.SubElement(address, 'AddressName').text = order.partner_shipping_id.name or 'Address Name'
            ET.SubElement(address, 'Address1').text = order.partner_shipping_id.street or ''
            ET.SubElement(address, 'Address2').text = order.partner_shipping_id.street2 or ''
            ET.SubElement(address, 'City').text = order.partner_shipping_id.city or ''
            ET.SubElement(address, 'State').text = order.partner_shipping_id.state_id.code or ''
            ET.SubElement(address, 'PostalCode').text = order.partner_shipping_id.zip or ''
            ET.SubElement(address, 'Country').text = order.partner_shipping_id.country_id.code or ''


        line_count = self.make_saleorder_line_xml_data(order, order_root)

        summary = ET.SubElement(order_root, 'Summary')
        ET.SubElement(summary, 'TotalLineItemNumber').text = str(line_count)

        return order_root


    @api.model
    def _do_export_sale_acknowledgement_xml(self, conn, sync_action_id, values):
        '''
        Performs the document synchronization for the new document code
        @param conn : sftp/ftp connection class.
        @param sync_action_id: recordset of type `edi.sync.action`
        @param values:dict of values that may be useful to various methods

        @return bool : return bool (True|False)
        '''
        conn._connect()
        conn.cd(sync_action_id.dir_path)
        # Get sale orders to be sent to EDI:
        # Get individual records passed when SO hits action_confirm() -> values['records']
        # or get all pending records when user runs the synchronization action manually
        orders = values.get('records') or self.env['sale.order'].sudo().search([('state','=','sale'),('x_edi_status','=','pending')])

        for order in orders:
            order_data = self.make_saleorder_xml_data(order)
            order_data = ET.ElementTree(order_data)

            if order_data:
                filename = '855_sale_%s.xml' % order.name.replace('/', '_')
                with open(filename, 'wb') as file:
                    order_data.write(file, pretty_print=True)

                filename = filename.strip()
                try:
                    with open(filename, 'rb') as file:
                        conn.upload_file(filename, file)
                        file.close()
                    order.write({'x_edi_status': 'sent', 'x_edi_date': fields.Datetime.now()})
                    order.sudo().message_post(body=_('Sale Order file created on the EDI server %s' % filename))
                    _logger.info('Sale Order file created on the server path of %s/%s' % (sync_action_id.dir_path, filename))
                except Exception as e:
                    order.write({'x_edi_status': 'fail'})
                    _logger.error('file not uploaded %s' % e)
                os.remove(filename)
            self.flush()
        conn._disconnect()
        return True
