# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


import logging
import os
import pprint
import pytz
from pytz import timezone

from datetime import datetime, timedelta
from lxml import etree as ET  # DOC : https://lxml.de/api/index.html

from odoo.exceptions import ValidationError
from odoo import api, fields, models, _

EDI_DATE_FORMAT = '%Y-%m-%d'

_logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)

ns = {'sps': 'http://www.spscommerce.com/RSX'}


class SyncDocumentType(models.Model):
    _inherit = 'sync.document.type'

    doc_code = fields.Selection(selection_add=[
        ('import_so_xml', '850 - Import Order (SPS Commerce XML)')
    ], ondelete={'import_so_xml': 'cascade'})

    def _is_new_order(self, orderheader, PO_number):
        """
        Returns True if the order is not a duplicate.
        First, it checks if the import claims to be a new order.
        Then, it checks if an order with the same PO number already exists in db
        """

        tset_purpose_code = self.get_ele_text(orderheader, 'TsetPurposeCode')
        primary_PO_type_code = self.get_ele_text(orderheader, 'PrimaryPOTypeCode')

        if tset_purpose_code == '00' or primary_PO_type_code in ['SA', 'NE']:
            if self.env['sale.order'].search([('x_po_number', '=', PO_number)]):
                return False

        return True

    def get_uom(self, order_id, uom_edi):
        """
        Choose a Unit of Measure based on the OrderQtyUOM provided in the EDI file.
        EA stands for Units and CA stands for cases
        """

        uom = self.env['uom.uom'].search([('x_edi_code', '=', uom_edi)])

        if not uom:
            if uom_edi not in ['EA', 'CA']:
                self.env['sale.order.line'].create({
                    'order_id': order_id,
                    'name': 'UoM of %s not found. Units automatically assigned.' % uom_edi,
                    'display_type': 'line_note'
                })
            uom = self.env['uom.uom'].search([('name', '=', 'Units')], limit=1)
            if not uom:
                raise ValidationError('Could not assign UoM. No unit named Units.')

        return uom

    def get_charges_allowances(self, chrg_allw_block):
        """Return a Charge/Allowance record or create one if a match is not found in the database"""

        data = {
            'indicator': self.get_ele_text(chrg_allw_block, 'AllowChrgIndicator'),
            'code': self.get_ele_text(chrg_allw_block, 'AllowChrgCode'),
            'amount': self.get_ele_text(chrg_allw_block, 'AllowChrgAmt'),
            'percent_qualifier': self.get_ele_text(chrg_allw_block, 'AllowChrgPercentQual'),
            'percent': self.get_ele_text(chrg_allw_block, 'AllowChrgPercent'),
            'handling_code': self.get_ele_text(chrg_allw_block, 'AllowChrgHandlingCode'),
        }

        charge_allow = self.env['charge.allowance'].search([
            ('indicator', '=', data['indicator']),
            ('code', '=', data['code']),
            ('amount', '=', data['amount']),
            ('percent_qualifier', '=', data['percent_qualifier']),
            ('percent', '=', data['percent']),
            ('handling_code', '=', data['handling_code']),
        ])

        if not charge_allow:
            charge_allow = self.env['charge.allowance'].create(data)

        return charge_allow

    def get_payment_terms(self, payment_terms, FOB_related_instruction=None):
        """
        Retrieves the corresponding payment term record from the database and
        returns the text contents for x_customer_payment_terms Text field. First tries to find a match by looking at the
        Terms Description field. If not found, it uses a "smarter" approach by looking at the rest of the fields.
        """
        terms_type = self.get_ele_text(payment_terms, 'TermsType')
        basis_date_code = self.get_ele_text(payment_terms, 'TermsBasisDateCode')
        discount_percentage = self.get_ele_text(payment_terms, 'TermsDiscountPercentage')
        discount_date = self.get_ele_text(payment_terms, 'TermsDiscountDate')
        discount_due_days = self.get_ele_text(payment_terms, 'TermsDiscountDueDays')
        net_due_date = self.get_ele_text(payment_terms, 'TermsNetDueDate')
        net_due_days = self.get_ele_text(payment_terms, 'TermsNetDueDays')
        terms_description = self.get_ele_text(payment_terms, 'TermsDescription')

        payment_term_id = self.env['account.payment.term'].search([('x_description', '=', terms_description)], limit=1)

        if not payment_term_id:
            # Immediate Payment
            if terms_type == '10':
                payment_term_id = self.env['account.payment.term'].search([]) \
                    .filtered(lambda p: p.line_ids.filtered(lambda line: line.value == 'balance' and line.days == 0))

            elif discount_percentage:
                # Retrieve the Odoo payment term record which lines match the EDI discount and the days
                payment_term_id = self.env['account.payment.term'].search([]) \
                    .filtered(
                    lambda p: p.line_ids.filtered(
                        lambda line: line.value == 'percent' and line.days == int(discount_due_days)) and p.line_ids.filtered(
                        lambda line: line.value == 'balance' and line.days == int(net_due_days or discount_due_days)))
            elif net_due_days:
                payment_term_id = self.env['account.payment.term'].search([]) \
                    .filtered(
                    lambda p: not p.line_ids.filtered(lambda line: line.value == 'percent') and p.line_ids.filtered(
                        lambda line: line.value == 'balance' and line.days == int(net_due_days)))

        x_customer_payment_terms = \
            'Terms Type: %s\nBasis Date Code: %s\nDiscount Percentage: %s\nDiscount Date: %s\nDiscount Due Days: %s\nNet Due Date: %s\nNet Due Days: %s\nTerms Description: %s\n' \
            % (terms_type, basis_date_code, discount_percentage, discount_date, discount_due_days, net_due_date,
               net_due_days, terms_description)

        if FOB_related_instruction is not None:
            FOB_pay_code = self.get_ele_text(FOB_related_instruction, 'FOBPayCode')
            FOB_location_qualifier = self.get_ele_text(FOB_related_instruction, 'FOBLocationQualifier')
            FOB_location_description = self.get_ele_text(FOB_related_instruction, 'FOBLocationDescription')

            x_customer_payment_terms += \
                'FOB Pay Code: %s\nFOB Location Qualifier: %s\nFOB Location Description: %s\n' \
                % (FOB_pay_code, FOB_location_qualifier, FOB_location_description)

        return x_customer_payment_terms, payment_term_id


    def prepared_sale_order_line_from_xml(self, line, order_id, partner, is_backorder=False):

        order_line = line.find('sps:OrderLine', ns)
        product_or_item_description = line.find('sps:ProductOrItemDescription', ns)
        physical_details = line.find('sps:PhysicalDetails', ns)
        x_line_sequence_number = self.get_ele_text(order_line, 'LineSequenceNumber')
        buyer_partnumber = self.get_ele_text(order_line, 'BuyerPartNumber')
        vendor_partnumber = self.get_ele_text(order_line, 'VendorPartNumber')
        barcode = self.get_ele_text(order_line, 'ConsumerPackageCode')  # The UPC is always passed in 'ConsumerPackageCode'
        x_consumer_package_code = self.get_ele_text(order_line, 'ConsumerPackageCode')
        x_ean = self.get_ele_text(order_line, 'EAN')
        x_gtin = self.get_ele_text(order_line, 'GTIN')
        product_id = order_line.find('sps:ProductID', ns)
        part_number = self.get_ele_text(product_id, 'PartNumber')
        name = self.get_ele_text(product_or_item_description, 'ProductDescription')

        Product = self.env['product.product']

        # If x_edi_code is not provided, choose 'Units' by default
        uom_edi = self.get_ele_text(order_line, 'OrderQtyUOM') or 'EA'
        uom = self.get_uom(order_id, uom_edi)

        x_pack_size = self.get_ele_text(physical_details, 'PackValue')

        product = Product.search([('barcode', '=', barcode)], limit=1)

        if not product:  # For variants, strip the leading and trailing characters
            product = Product.search([('barcode', '=', barcode[1:])], limit=1)

        if not product:  # For Case UPC, strip the leading and trailing characters
            product = Product.search([('barcode', '=', barcode[1:-1])], limit=1)

        if not product:
            _logger.info('Product Not found FROM the EDI - Barcode: %s' % barcode)
            # Create a note with the UPC number coming from EDI, Sales Price of the Product, Unit of Measure and the Quantity.
            line_data = {
                'order_id': order_id,
                'name': 'PRODUCT NOT FOUND - UPC/barcode: %s, EAN: %s, GTIN: %s Price: %s, UoM: %s, Quantity: %s, LineSequence#: %s' % (
                    barcode, x_ean, x_gtin, self.get_ele_text(order_line, 'PurchasePrice'), uom_edi,
                    self.get_ele_text(order_line, 'OrderQty'), x_line_sequence_number),
                'display_type': 'line_note',
                'price_unit': self.get_ele_text(order_line, 'PurchasePrice') or 0,
                'product_uom_qty': int(self.get_ele_text(order_line, 'OrderQty')) or 1,
                'product_uom': uom_edi or '',
            }
            return line_data

        product.sudo().write({'x_gtin': x_gtin})
        product.sudo().write({'x_ean': x_ean})

        # Charges Allowances on Line Level
        x_charges_allowances = line.find('sps:ChargesAllowances', ns)
        x_charges_allowances_text = ''
        if x_charges_allowances:
            x_allow_chrg_indicator = self.get_ele_text(x_charges_allowances, 'AllowChrgIndicator')
            x_allow_chrg_code = self.get_ele_text(x_charges_allowances, 'AllowChrgCode')
            x_reference_identification = self.get_ele_text(x_charges_allowances, 'ReferenceIdentification')
            x_charges_allowances_text = '%s\n%s\n%s\n\n' % (
                x_allow_chrg_indicator, x_allow_chrg_code, x_reference_identification)

        package = None
        quantity = int(self.get_ele_text(order_line, 'OrderQty'))
        if uom_edi == 'CA' and product.packaging_ids:
            package = product.packaging_ids.sorted(key=lambda r: r.create_date, reverse=True)[0]
            if package.qty:
                quantity *= package.qty

        order_in_cases = package and package.qty and uom_edi == 'CA'
        x_edi_price = float(self.get_ele_text(order_line, 'PurchasePrice')) or 0
        price_pricelist = self.env['sale.order'].get_gross_selling_price(partner, product, package)
        if price_pricelist != x_edi_price:
            self.env['sale.order.line'].create({
                'order_id': order_id,
                'name': 'WARNING: Price mismatch between Odoo and EDI - Product: %s, Package: %s, EDI Price: %s, Selling Price: %s' % (
                    product.name, package.name if package else 'None', x_edi_price, price_pricelist),
                'display_type': 'line_note'
            })

        # EDI price will be the price per case whenever the partner orders in Cases
        if order_in_cases and not partner.x_price_in_cases:
            x_edi_price *= package.qty

        if order_in_cases:
            if partner.x_price_in_cases:
                case_price = price_pricelist
                price_unit = price_pricelist / package.qty
            else:
                case_price = price_pricelist * package.qty
                price_unit = price_pricelist
        else:
            case_price = price_unit = price_pricelist

        # Get payment terms
        payment_terms = line.find('sps:PaymentTerms', ns)
        x_customer_payment_terms = ''
        payment_term_id = None
        if payment_terms is not None:
            x_customer_payment_terms, payment_term_id = self.get_payment_terms(payment_terms)

        # Taxes
        taxes = line.find('sps:Taxes', ns)
        if taxes:
            x_tax_code = self.get_ele_text(taxes, 'TaxTypeCode') or ''
            x_tax_percent = self.get_ele_text(taxes, 'TaxPercent') or ''
            x_tax_id = self.get_ele_text(taxes, 'TaxID') or ''

        item_status_code = 'IA'
        if case_price != x_edi_price:
            item_status_code = 'IP'
        if is_backorder:
            item_status_code = 'IB'

        line_data = {
            'order_id': order_id,
            'product_id': product.id,
            'name': name or product.name,
            'product_uom_qty': quantity or 1,
            'product_uom': uom.id,
            'price_unit': price_unit,
            'x_case_price': case_price,
            'x_edi_price': x_edi_price,
            'display_type': '',
            'x_pack_size': x_pack_size or 1,
            'x_consumer_package_code': x_consumer_package_code,
            'x_line_sequence_number': x_line_sequence_number,
            'x_part_number': part_number,
            'x_vendor_part_number': vendor_partnumber,
            'x_buyer_part_number': buyer_partnumber,
            'product_packaging_id': package.id if package else None,
            'x_charges_allowances': x_charges_allowances_text,
            'x_payment_terms': x_customer_payment_terms,
            'x_tax_code': x_tax_code if taxes else 'TX',
            'x_tax_percent': x_tax_percent if taxes else '0',
            'x_tax_id': x_tax_id if taxes else '0',
            'x_item_status_code': item_status_code
        }
        return line_data

    def get_ele_text(self, elemt, node_name):
        if elemt is None:
            return ''
        ele_node = elemt.find('sps:%s' % (node_name), ns)
        vals = str(ele_node.text) if ele_node is not None and ele_node.text is not None else ''
        _logger.info('read: `%s`: `%s`' % (node_name, vals))
        return vals[0] if len(vals) == 1 else vals

    def _add_contact_to_list(self, x_all_contacts_list, contact):
        code = self.get_ele_text(contact, 'ContactTypeCode') or ''
        contact_code = 'Buyer Contact' if code == 'BD' else 'Receiving Contact'
        contact_name = self.get_ele_text(contact, 'ContactName') or ''
        contact_phone = self.get_ele_text(contact, 'PrimaryPhone') or ''
        contact_tuple = (contact_code, contact_name, contact_phone)
        if contact_tuple not in x_all_contacts_list:
            x_all_contacts_list.append(contact_tuple)

    def _add_address_to_list(self, x_addresses, address):
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


    def get_contacts(self, contacts, addresses, trading_partnerid):
        """
        Returns the following contact records to be assigned to the sale order:
        Customer (partner_id)
        Shipping Address (partner_shipping_id)
        Invoice Address (partner_invoice_id)
        Addresses (x_addresses)
        Contacts (x_all_contacts)

        @param contacts: Contacts at Header level
        """
        x_all_contacts = x_addresses = ''
        x_all_contacts_list = []

        for contact in contacts:
            self._add_contact_to_list(x_all_contacts_list, contact)

        main_partner = self.env['res.partner'].sudo().search([('trading_partnerid', '=', trading_partnerid),
                                                              ('is_company', '=', True)],
                                                             limit=1)
        partner_shipping_id = partner_invoice_id = ''
        for address in addresses:
            self._add_address_to_list(x_addresses, address)

            contact = address.find('sps:Contacts', ns) or None
            if contact:
                self._add_contact_to_list(x_all_contacts_list, contact)

            address_id = self.env['res.partner'].search(
                [('x_address_location_number', '=', self.get_ele_text(address, 'AddressLocationNumber'))], limit=1)

            address_type = self.get_ele_text(address, 'AddressTypeCode')
            contact_type = 'delivery' if address_type == 'ST' else 'invoice' if address_type == 'BT' else 'contact'

            if not address_id and contact_type in ['delivery', 'invoice']:
                country = self.env['res.country'].search([('code', '=', self.get_ele_text(address, 'Country')[:2])],
                                                         limit=1)
                state = self.env['res.country.state'].search(
                    [('code', '=', self.get_ele_text(address, 'State')), ('country_id', '=', country.id)], limit=1)
                partner_data = {
                    'name': self.get_ele_text(address, 'AddressName'),
                    'parent_id': main_partner.id,
                    'trading_partnerid': trading_partnerid,
                    'x_location_code_qualifier': self.get_ele_text(address, 'LocationCodeQualifier'),
                    'x_address_location_number': self.get_ele_text(address, 'AddressLocationNumber'),
                    'country_id': country.id,
                    'state_id': state.id,
                    'street': self.get_ele_text(address, 'Address1'),
                    'street2': self.get_ele_text(address, 'Address2'),
                    'city': self.get_ele_text(address, 'City'),
                    'zip': self.get_ele_text(address, 'PostalCode'),
                    'type': contact_type,
                }
                address_id = self.env['res.partner'].create(partner_data)

            if contact_type == 'delivery':
                partner_shipping_id = address_id

            if contact_type == 'invoice':
                partner_invoice_id = address_id

        # Convert list of contacts to multiline text field
        for contact in x_all_contacts_list:
            x_all_contacts += 'Type: %s\nName: %s\nPhone: %s\n\n' % (contact[0], contact[1], contact[2])

        partner_shipping_id = partner_shipping_id or main_partner
        partner_invoice_id = partner_invoice_id or main_partner

        return main_partner, partner_shipping_id, partner_invoice_id, x_addresses, x_all_contacts

    def convert_TZ_UTC(self, TZ_datetime, is_datetime=False):
        """Convert datetime from user timezone to UTZ"""
        tz = pytz.timezone(self.env.user.tz or pytz.utc)
        format = "%Y-%m-%d %H:%M:%S"
        local_datetime_format = "%Y-%m-%d"
        now_utc = datetime.utcnow()  # Current time in UTC
        now_timezone = now_utc.astimezone(tz)  # Convert to current user time zone
        UTC_OFFSET_TIMEDELTA = datetime.strptime(now_utc.strftime(format), format) - datetime.strptime(now_timezone.strftime(format), format)
        if is_datetime:
            local_datetime_format = format
        local_datetime = datetime.strptime(TZ_datetime, local_datetime_format)
        result_utc_datetime = local_datetime + UTC_OFFSET_TIMEDELTA
        return result_utc_datetime.strftime(format)


    def prepared_order_from_xml(self, order):
        header = order.find('sps:Header', ns)
        summary = order.find('sps:Summary', ns)

        # OrderHeader data
        orderheader = header.find('sps:OrderHeader', ns)
        trading_partnerid = self.get_ele_text(orderheader, 'TradingPartnerId')
        po_number = self.get_ele_text(orderheader, 'PurchaseOrderNumber')
        tset_purpose_code = self.get_ele_text(orderheader, 'TsetPurposeCode')
        primary_PO_type_code = self.get_ele_text(orderheader, 'PrimaryPOTypeCode')
        vendor = self.get_ele_text(orderheader, 'Vendor')
        department = self.get_ele_text(orderheader, 'Department')

        # Check if current order is backorder
        backorder_origin = self.env['sale.order'].sudo().search(
            [('x_po_number', '=', po_number), ('x_backorder_origin', '=', None)], limit=1)

        # Order date - Converted to UTC
        date_order = self.get_ele_text(orderheader, 'PurchaseOrderDate')
        date_order = self.convert_TZ_UTC(date_order)

        # Get contacts
        contacts = header.findall('sps:Contacts', ns)
        addresses = header.findall('sps:Address', ns)
        partner, partner_shipping_id, partner_invoice_id, x_addresses, x_all_contacts = self.get_contacts(contacts,
                                                                                                          addresses,
                                                                                                          trading_partnerid)

        # Get payment terms
        payment_terms = header.find('sps:PaymentTerms', ns)
        FOB_related_instruction = header.find('sps:FOBRelatedInstruction', ns)
        x_customer_payment_terms = ''
        payment_term_id = ''
        if payment_terms is not None:
            x_customer_payment_terms, payment_term_id = self.get_payment_terms(payment_terms, FOB_related_instruction)

        # Get dates
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


        carrier_information = header.find('sps:CarrierInformation', ns)
        references = header.find('sps:References', ns)
        notes = header.find('sps:Notes', ns)
        x_note_code = self.get_ele_text(notes, 'NoteCode')
        x_note_code = x_note_code if x_note_code in ('GEN', 'SHP') else 'GEN'

        # Charges Allowances on Header Level
        x_charges_allowances = []
        for charge_allow in header.findall('sps:ChargesAllowances', ns):
            charge_record = self.get_charges_allowances(charge_allow)
            x_charges_allowances.append(charge_record.id)

        edi_user = self.env['res.users'].browse(1)  # Use Odoobot for orders created from EDI

        order_data = {
            'partner_id': partner.id,
            'x_po_number': po_number,
            'x_backorder_origin': backorder_origin.id or None,
            'x_tset_purpose_code': tset_purpose_code if tset_purpose_code in ['00', '06'] else 'NA',
            'x_primary_PO_type_code': primary_PO_type_code if primary_PO_type_code in ['SA', 'NE', 'PR', 'RO', 'CF'] else 'NA',
            'x_vendor': vendor,
            'x_department': department,
            'date_order': date_order,
            'partner_invoice_id': partner_invoice_id.id,
            'partner_shipping_id': partner_shipping_id.id,
            'x_all_contacts': x_all_contacts,
            'x_addresses': x_addresses,
            'payment_term_id': payment_term_id.id if payment_term_id else None,
            'x_customer_payment_terms': x_customer_payment_terms or '',
            'x_date_time_qualifier': x_date_time_qualifier or '',
            'commitment_date': specific_date if x_date_time_qualifier == '002' else None,
            'x_requested_pickup_date': specific_date if x_date_time_qualifier == '118' else None,
            'x_additional_date': specific_date if x_date_time_qualifier not in ('002', '118') else None,
            'x_carrier_trans_method_code': self.get_ele_text(carrier_information, 'CarrierTransMethodCode'),
            'x_carrier_routing': self.get_ele_text(carrier_information, 'CarrierRouting'),
            'x_reference_qual': self.get_ele_text(references, 'ReferenceQual') if self.get_ele_text(references,'ReferenceQual') in ['12', 'AH', 'IT', 'CT'] else 'NA',
            'x_reference_id': self.get_ele_text(references, 'ReferenceID'),
            'x_description': self.get_ele_text(references, 'Description'),
            'x_note_code': x_note_code if x_note_code in ['GEN', 'SHP'] else 'NA',
            'note': self.get_ele_text(notes, 'Note'),
            'x_charges_allowances': [[6, 0, x_charges_allowances]],
            'amount_total': self.get_ele_text(summary, 'TotalAmount'),
            'x_total_line_item_number': self.get_ele_text(summary, 'TotalLineItemNumber'),
            'user_id': edi_user.id,
        }
        return order_data

    def _do_import_so_xml(self, conn, sync_action_id, values):
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

        SaleOrder = self.env['sale.order'].sudo()
        SaleOrderLine = self.env['sale.order.line'].sudo()
        ResPartner = self.env['res.partner'].sudo()

        for file in files:
            if not file.endswith('.xml'):
                continue

            file_data = conn.download_file(file)

            orders = ET.fromstring(file_data)
            # Skip the file if it is not an 850. It is a 945.
            if 'Orders' not in orders.tag:
                continue
            for order_elem in orders:
                header = order_elem.find('sps:Header', ns)
                orderheader = header.find('sps:OrderHeader', ns)
                trading_partnerid = self.get_ele_text(orderheader, 'TradingPartnerId')

                PO_number = self.get_ele_text(orderheader, 'PurchaseOrderNumber')

                # Check for duplicates. First see if the import claims to be a new order. Then check if duplicate order already exists in db
                if not self._is_new_order(orderheader, PO_number):
                    _logger.warning('Order already created with PO number %s' % PO_number)
                    continue

                trading_partner = ResPartner.search([('trading_partnerid', '=', trading_partnerid),
                                                     ('is_company', '=', True)], limit=1)
                if not trading_partner:
                    _logger.warning('Trading Partner not found for this ID: %s' % trading_partner)
                    continue

                order = SaleOrder.create(self.prepared_order_from_xml(order_elem))

                if order:
                    line_item = order_elem.findall('sps:LineItem', ns)
                    line_count = 0
                    for line in line_item:
                        line_data = self.prepared_sale_order_line_from_xml(line, order.id, trading_partner,
                                                                           is_backorder=len(order.x_backorder_origin))
                        SaleOrderLine.create(line_data)  # line is one element <OrderLine>
                        line_count = line_count + 1
                    order.write({'x_total_line_item_number': line_count})
                    order.flush()
                    order.sudo().message_post(body=_('Sale Order Created from the EDI File of: %s' % file))

        conn._disconnect()
        return True
