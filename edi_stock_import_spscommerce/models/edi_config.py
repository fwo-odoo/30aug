# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import os
import pprint
import pytz
import time

from datetime import datetime, date, timedelta
from lxml import etree as ET  # DOC : https://lxml.de/api/index.html
from math import ceil

from odoo.exceptions import ValidationError, UserError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT
from odoo import api, fields, models, _

EDI_DATE_FORMAT = '%Y-%m-%d'

_logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)

ns = {'sps': 'http://www.spscommerce.com/RSX'}


class SyncDocumentType(models.Model):
    _inherit = 'sync.document.type'

    def get_uom(self, order_id, uom_edi):
        """ Choose a Unit of Measure based on the OrderQtyUOM provided in the EDI file.
        EA stands for Units and CA stands for cases"""

        uom = self.env['uom.uom'].search([('x_edi_code', '=', uom_edi)])
        if not uom:
            uom = self.env['uom.uom'].search([('name', '=', 'Units')], limit=1)
        if not uom:
            raise ValidationError('Could not assign UoM. No unit named Units.')

        return uom


    def prepared_shipment_line_from_xml(self, line, shipment_id, partner, pallet):

        order_line = line.find('sps:ShipmentLine', ns)
        product_or_item_description = line.find('sps:ProductOrItemDescription', ns)
        physical_details = line.find('sps:PhysicalDetails', ns)
        references = line.find('sps:References', ns)

        x_line_sequence_number = self.get_ele_text(order_line, 'LineSequenceNumber')
        buyer_partnumber = self.get_ele_text(order_line, 'BuyerPartNumber')
        vendor_partnumber = self.get_ele_text(order_line, 'VendorPartNumber')
        barcode = self.get_ele_text(order_line, 'ConsumerPackageCode')  # The UPC is always passed in 'ConsumerPackageCode'
        x_consumer_package_code = self.get_ele_text(order_line, 'ConsumerPackageCode')
        x_ean = self.get_ele_text(order_line, 'EAN')
        x_gtin = self.get_ele_text(order_line, 'GTIN')
        # product_id = order_line.find('sps:ProductID', ns)
        # part_number = self.get_ele_text(product_id, 'PartNumber')
        name = self.get_ele_text(product_or_item_description, 'ProductDescription')
        product_product = self.env['product.product']


        # If x_edi_code is not provided, choose 'Units' by default
        uom_edi = self.get_ele_text(order_line, 'ShipQtyUOM') or 'EA'
        x_pack_size = self.get_ele_text(physical_details, 'PackValue')
        uom = self.get_uom(shipment_id, uom_edi)

        product = product_product.search([('barcode', '=', barcode)], limit=1)

        if not product:  # For variants, strip the leading and trailing characters
            product = product_product.search([('barcode', '=', barcode[1:])], limit=1)

        if not product:  # For Case UPC, strip the leading and trailing characters
            product = product_product.search([('barcode', '=', barcode[1:-1])], limit=1)

        if not product:
            _logger.info('Product Not found FROM the EDI:\n Barcode: %s' % (barcode))
            product = self.env.ref('edi_sale_spscommerce.edi_product_product_error')

        product.sudo().write({'x_gtin': x_gtin})
        product.sudo().write({'x_ean': x_ean})

        quantity = float(self.get_ele_text(order_line, 'ShipQty'))
        package = None
        if uom_edi == 'CA' and product.packaging_ids:
            package = product.packaging_ids.sorted(key=lambda r: r.create_date, reverse=True)[0]
            if package.qty:
                quantity *= package.qty

        order_in_cases = package and package.qty and uom_edi == 'CA'

        # Get payment terms
        payment_terms = line.find('sps:PaymentTerms', ns)
        x_customer_payment_terms = ''
        payment_term_id = ''
        if payment_terms is not None:
            x_customer_payment_terms, payment_term_id = self.get_payment_terms(payment_terms)

        # Taxes
        taxes = line.find('sps:Taxes', ns)
        if taxes:
            x_tax_code = self.get_ele_text(taxes, 'TaxTypeCode') or ''
            x_tax_percent = self.get_ele_text(taxes, 'TaxPercent') or ''
            x_tax_id = self.get_ele_text(taxes, 'TaxID') or ''


        line_data = {
            'picking_id': shipment_id,
            'product_id': product.id,
            'product_uom_qty': quantity or 1,
            'product_uom': product.uom_id.id,
            'location_id': self.env.user._get_default_warehouse_id().lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'name': name or 'EDI description unavaliable',
            'product_uom': uom.id,
            'x_consumer_package_code': x_consumer_package_code,
            'x_line_sequence_number': x_line_sequence_number,
            'x_vendor_part_number': vendor_partnumber,
            'x_buyer_part_number': buyer_partnumber,
        }
        return line_data

    def get_contacts(self, contacts, addresses, trading_partnerid):
        x_all_contacts = ''
        x_addresses = ''
        x_all_contacts_list = []
        contact_name_main = contact_phone = contact_tuple = ''
        # Contacts at Header level
        for contact in contacts:

            code = self.get_ele_text(contact, 'ContactTypeCode') or ''
            contact_code = 'Buyer Contact' if code == 'BD' else 'Receiving Contact'  # dd undefined code
            contact_name_main = self.get_ele_text(contact, 'ContactName') or ''
            contact_phone = self.get_ele_text(contact, 'PrimaryPhone') or ''
            contact_tuple = (contact_code, contact_name_main, contact_phone)
            if contact_tuple not in x_all_contacts_list:
                x_all_contacts_list.append(contact_tuple)

        existing_partner = self.env['res.partner'].sudo().search([('trading_partnerid', '=', trading_partnerid),
                                                                  ('is_company', '=', True)],
                                                                  limit=1)

        partner_shipping_id = ''
        partner_invoice_id = ''
        # Contacts at Address level
        for address in addresses:
            contact_name = existing_partner and existing_partner.name or contact_name_main or ('EDI %s' % trading_partnerid)
            contact = address.find('sps:Contacts', ns) or None
            if contact:
                code = self.get_ele_text(contact, 'ContactTypeCode')
                contact_code = 'Buyer Contact' if code == 'BD' else 'Receiving Contact'
                contact_name = self.get_ele_text(contact, 'ContactName') or 'EDI Contact'
                contact_phone = self.get_ele_text(contact, 'PrimaryPhone') or ''

                contact_tuple = (contact_code, contact_name, contact_phone)
                if contact_tuple not in x_all_contacts_list:
                    x_all_contacts_list.append((contact_code, contact_name, contact_phone))

            country = self.env['res.country'].search([('code', '=', self.get_ele_text(address, 'Country')[:2])], limit=1)
            state = self.env['res.country.state'].search([('code', '=', self.get_ele_text(address, 'State')), ('country_id', '=', country.id)], limit=1)

            address_type = self.get_ele_text(address, 'AddressTypeCode')
            type = 'delivery' if address_type == 'ST' else 'invoice' if address_type == 'BT' else 'contact'

            x_addresses += 'AddressName: %s\nAddressTypeCode: %s\nLocationCodeQualifier: %s\nAddressLocationNumber: %s\nStreet1: %s\nStreet2: %s\nCity: %s\nPostalCode: %s\nCountry: %s\n\n' % (
                self.get_ele_text(address, 'AddressName') or '',
                self.get_ele_text(address, 'AddressTypeCode') or '',
                self.get_ele_text(address, 'LocationCodeQualifier') or '',
                self.get_ele_text(address, 'AddressLocationNumber') or '',
                self.get_ele_text(address, 'Address1') or '',
                self.get_ele_text(address, 'Address2') or '',
                self.get_ele_text(address, 'City') or '',
                self.get_ele_text(address, 'PostalCode') or '',
                self.get_ele_text(address, 'Country') or '')

            existing_address = self.env['res.partner'].search(
                [('x_address_location_number', '=', self.get_ele_text(address, 'AddressLocationNumber')),
                 ('name', '=', self.get_ele_text(address, 'AddressName')),
                 ('street', '=', self.get_ele_text(address, 'Address1'))], limit=1)
            new_address = ''
            if not existing_address:
                # new_address = self.env.ref('edi_sale.res_partner_error', raise_if_not_found=False)
                partner_data = {
                    'name': self.get_ele_text(address, 'AddressName'),
                    'trading_partnerid': trading_partnerid,
                    # 'x_contact_type_code': code,
                    'x_location_code_qualifier': self.get_ele_text(address, 'LocationCodeQualifier'),
                    'x_address_location_number': self.get_ele_text(address, 'AddressLocationNumber'),
                    'phone': contact_phone,
                    'country_id': country.id,
                    'state_id': state.id,
                    'street': self.get_ele_text(address, 'Address1'),
                    'street2': self.get_ele_text(address, 'Address2'),
                    'city': self.get_ele_text(address, 'City'),
                    'zip': self.get_ele_text(address, 'PostalCode'),
                    'type': type,
                }
                new_address = self.env['res.partner'].create(partner_data)

            if type == 'delivery':
                partner_shipping_id = new_address or existing_address

            if type == 'invoice':
                partner_invoice_id = new_address or existing_address

            if not existing_partner:
                partner_data = {
                    'name': self.get_ele_text(address, 'AddressName'),
                    'trading_partnerid': trading_partnerid,
                    'x_location_code_qualifier': self.get_ele_text(address, 'LocationCodeQualifier'),
                    'x_address_location_number': self.get_ele_text(address, 'AddressLocationNumber'),
                    'phone': contact_phone,
                    'country_id': country.id,
                    'state_id': state.id,
                    'street': self.get_ele_text(address, 'Address1'),
                    'street2': self.get_ele_text(address, 'Address2'),
                    'city': self.get_ele_text(address, 'City'),
                    'zip': self.get_ele_text(address, 'PostalCode'),
                    'type': type,
                    'company_type': 'company',
                }
                existing_partner = self.env['res.partner'].create(partner_data)

        # Convert list of contacts to multiline text field
        for contact in x_all_contacts_list:
            x_all_contacts += 'Type: %s\nName: %s\nPhone: %s\n\n' % (contact[0], contact[1], contact[2])

        partner_sale = existing_partner or partner_shipping_id or partner_invoice_id  # or self.env.ref('edi_sale.res_partner_error', raise_if_not_found=False)
        partner_shipping_id = partner_shipping_id or partner_sale
        partner_invoice_id = partner_invoice_id or partner_sale

        return partner_sale, partner_shipping_id, partner_invoice_id, x_addresses, x_all_contacts

    def parse_datetime(self, date=None, time=None):
        if not date:
            return fields.Datetime.now()
        if time:
            return self.convert_TZ_UTC('%s %s' % (date, time), is_datetime=True)
        else:
            return self.convert_TZ_UTC(date)

    def assign_lots_to_lines(self, shipment_id, shipment):
        """ Assign Lot Numbers to stock.move.lines based on the ReferenceIDs provided in the EDI file"""

        order_level = shipment.find('sps:OrderLevel', ns)
        packs = order_level.findall('sps:PackLevel', ns)

        for pack in packs:
            items = pack.findall('sps:ItemLevel', ns)
            for item in items:
                line = item.find('sps:ShipmentLine', ns)
                references = item.find('sps:References', ns)
                if references is not None and self.get_ele_text(references, 'ReferenceQual') == 'LT':
                    lot_ref = self.get_ele_text(references, 'ReferenceID')
                    move = shipment_id.move_ids_without_package.filtered(lambda move: move.product_id.barcode == self.get_ele_text(line, 'ConsumerPackageCode') and
                                                                          move.x_line_sequence_number == self.get_ele_text(line, 'LineSequenceNumber'))

                    lot_id = self.env['stock.production.lot'].search([('name', '=', lot_ref), ('product_id', '=', move.product_id.id)])
                    if not lot_id:
                        lot_id = self.env['stock.production.lot'].create({
                            'product_id': move.product_id.id,
                            'name': lot_ref,
                            'company_id': self.env.company.id,
                        })
                    move.move_line_ids.write({'lot_id': lot_id.id})

    def assign_pallets_to_lines(self, shipment_id, shipment):
        """ Assign Pallet Numbers to stock.move.lines based on the ReferenceIDs provided in the EDI file"""

        order_level = shipment.find('sps:OrderLevel', ns)
        packs = order_level.findall('sps:PackLevel', ns)

        for pack in packs:
            marks = pack.find('sps:MarksAndNumbersCollection', ns)
            if marks is not None and self.get_ele_text(marks, 'MarksAndNumbersQualifier1') == 'W':
                pallet_num = self.get_ele_text(marks, 'MarksAndNumbers1')
                pallet_id = self.env['stock.quant.package'].search([('name', '=', pallet_num)], limit=1)
                if not pallet_id:
                    pallet_id = self.env['stock.quant.package'].create({'name': pallet_num})

                items = pack.findall('sps:ItemLevel', ns)
                for item in items:
                    line = item.find('sps:ShipmentLine', ns)
                    move = shipment_id.move_ids_without_package.filtered(lambda move: move.product_id.barcode == self.get_ele_text(line, 'ConsumerPackageCode') and
                                                                          move.x_line_sequence_number == self.get_ele_text(line, 'LineSequenceNumber'))

                    move.move_line_ids.write({'result_package_id': pallet_id.id})

    def prepared_shipment_from_xml(self, shipment):
        header = shipment.find('sps:Header', ns)
        summary = shipment.find('sps:Summary', ns)

        # OrderHeader data
        shipmentheader = header.find('sps:ShipmentHeader', ns)
        shipment_identification = self.get_ele_text(shipmentheader, 'ShipmentIdentification')

        ship_date = self.get_ele_text(shipmentheader, 'ShipDate')
        ship_time = self.get_ele_text(shipmentheader, 'ShipmentTime')
        scheduled_date = self.parse_datetime(ship_date, ship_time)

        trading_partnerid = self.get_ele_text(shipmentheader, 'TradingPartnerId')

        order_level = shipment.find('sps:OrderLevel', ns)
        order_header = order_level.find('sps:OrderHeader', ns)

        po_number = self.get_ele_text(order_header, 'PurchaseOrderNumber')
        so_origin = self.env['sale.order'].search([('x_po_number', '=', po_number)])
        if len(so_origin) > 1:
            _logger.info('Skipping 945 file. Found more than one Sale Order record with PO Number: %s' % po_number)
            return False
        tset_purpose_code = self.get_ele_text(shipmentheader, 'TsetPurposeCode')
        vendor = self.get_ele_text(order_header, 'Vendor')

        # Order date
        date_order = self.get_ele_text(order_header, 'PurchaseOrderDate')
        date_order = self.convert_TZ_UTC(date_order)

        # Get contacts #
        contacts = header.findall('sps:Contacts', ns)

        addresses = header.findall('sps:Address', ns)
        partner, partner_shipping_id, partner_invoice_id, x_addresses, x_all_contacts = self.get_contacts(contacts,
                                                                                                          addresses,
                                                                                                          trading_partnerid)
        dates = header.findall('sps:Dates', ns)
        for date in dates:
            x_date_time_qualifier = self.get_ele_text(date, 'DateTimeQualifier')
            specific_date = ''
            if date is not None:
                date_date = self.get_ele_text(date, 'Date')
                date_time = self.get_ele_text(date, 'Time')
                if date_time:
                    specific_date = self.convert_TZ_UTC('%s %s' % (date_date, date_time), is_datetime=True)
                else:
                    specific_date = self.convert_TZ_UTC(date_date)

        # Carrier Information
        carrier_information = header.find('sps:CarrierInformation', ns)

        contacts = header.find('sps:Contacts', ns)
        contact_name = contact_phone = ''
        if self.get_ele_text(contacts, 'ContactTypeCode') == 'DI':
            contact_name = self.get_ele_text(contacts, 'ContactName')
            contact_phone = self.get_ele_text(contacts, 'PrimaryPhone')

        edi_user = self.env['res.users'].browse(1)  # Use Odoobot for orders created from EDI

        quantity_and_weight = header.find('sps:QuantityAndWeight', ns)

        data = {
            'partner_id': partner.id,  # existing_partner.id or partner.id,
            'picking_type_id': self.env.user._get_default_warehouse_id().out_type_id.id,
            'location_id': self.env.user._get_default_warehouse_id().lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'x_shipment_identification': shipment_identification,
            'scheduled_date': scheduled_date,
            'origin': so_origin.name,
            'x_all_contacts': x_all_contacts,
            'x_bill_of_lading_number': self.get_ele_text(shipmentheader, 'BillOfLadingNumber'),
            'x_contact_name': contact_name,
            'x_contact_phone': contact_phone,
            'x_carrier_trans_method_code': self.get_ele_text(carrier_information, 'CarrierTransMethodCode'),
            'x_carrier_alpha_code': self.get_ele_text(carrier_information, 'CarrierAlphaCode'),
            'x_carrier_routing': self.get_ele_text(carrier_information, 'CarrierRouting'),
            'user_id': edi_user.id,
        }
        return data

    def _do_import_shipping_xml(self, conn, sync_action_id, values):
        '''
        Performs the document synchronization for the new document code
        @param conn : sftp/ftp connection class.
        @param sync_action_id: recordset of type `edi.sync.action`
        @param values:dict of values that may be useful to various methods

        @return bool : return bool (True|False)
        '''
        conn._connect()
        conn.cd(sync_action_id.dir_path)
        files = conn.ls()
        if not files:
            _logger.warning('Directory on host is empty')

        StockPicking = self.env['stock.picking'].sudo()
        SaleOrder = self.env['sale.order'].sudo()
        ResPartner = self.env['res.partner'].sudo()

        for file in files:
            if not file.endswith('.xml'):
                continue
            file_path = os.path.join(sync_action_id.dir_path, file)
            temp_file = 'temp.xml'
            if sync_action_id.config_id.ftp_portocol == 'ftp':
                file_data = conn.download_file(file)
            else:
                file_data = conn._conn.getfo(file, temp_file)

            shipment_elem = ET.fromstring(file_data)
            if 'Shipment' not in shipment_elem.tag:
                continue

            header = shipment_elem.find('sps:Header', ns)
            if not header:
                # The file is not a 945. It is an 850 Sale Order.
                break
            shipmentheader = header.find('sps:ShipmentHeader', ns)

            order_level = shipment_elem.find('sps:OrderLevel', ns)
            order_header = order_level.find('sps:OrderHeader', ns)
            PO_number = self.get_ele_text(order_header, 'PurchaseOrderNumber')
            so_origin = SaleOrder.search([('x_po_number', '=', PO_number)], limit=1)
            if not so_origin:
                _logger.warning('Origin Sale Order not found with PO Number %s' % PO_number)
                continue

            data = self.prepared_shipment_from_xml(shipment_elem)
            shipment = None
            if data:
                shipment = StockPicking.create(data)

            if shipment:
                packs = order_level.findall('sps:PackLevel', ns)
                for pack in packs:
                    marks_and_numbers = pack.find('sps:MarksAndNumbersCollection', ns)
                    pallet_number = self.get_ele_text(marks_and_numbers, 'MarksAndNumbers1')
                    pallet = self.env['stock.quant.package'].create({'name': pallet_number})

                    line_item = pack.findall('sps:ItemLevel', ns)
                    for line in line_item:
                        line_data = self.prepared_shipment_line_from_xml(line, shipment.id, shipment.partner_id, pallet)
                        self.env['stock.move'].create(line_data)  # line is one element <ShipmentLine>

                    # Create the stock.move.lines
                    shipment.action_confirm()
                    shipment.action_assign()

                    self.assign_lots_to_lines(shipment, shipment_elem)
                    self.assign_pallets_to_lines(shipment, shipment_elem)
                    shipment.write({'sale_id': so_origin.id})

                    shipment.flush()
                    shipment.sudo().message_post(body=_('Delivery Order Created from the EDI File of: %s' % file))

        conn._disconnect()
        return True
