import pandas as pd
from kohle.plugin.importer_plugin import StatementImporterPlugin


class DeustcheBankStatementImporter(StatementImporterPlugin):
    @property
    def name(self) -> str:
        return "kohle-deutsche-bank"

    def import_statement(self, csv_path) -> pd.DataFrame:
        df = pd.read_csv(csv_path, header=4, sep=';', encoding='ISO-8859-1') \
               .pipe(lambda df: df.rename(columns={
                   'Beneficiary / Originator': 'beneficiary',
                   'Payment Details': 'details',
                   'Debit': 'debit',
                   'Credit': 'credit',
                   'IBAN': 'iban',
                   'Booking date': 'booking_date',
                   'Value date': 'value_date',
                   'Transaction Type': 'transaction_type',
                   'BIC': 'bic',
                   'Customer Reference': 'customer_reference',
                   'Mandate Reference': 'mandate_reference',
                   'Creditor ID': 'creditor_id',
                   'Compensation amount': 'compensation_amount',
                   'Original Amount': 'original_amount',
                   'Ultimate creditor': 'ultimate_creditor',
                   'Number of transactions': 'number_of_transactions',
                   'Number of cheques': 'number_of_cheques',
                   'Currency': 'currency'
                   })) \
                .fillna({ 'debit': 0, 'credit': 0 }) \
                .drop(columns=[
                    'beneficiary', 'details', 'iban', 'booking_date', 'value_date',
                    'bic', 'customer_reference', 'mandate_reference', 'creditor_id',
                    'compensation_amount', 'original_amount', 'ultimate_creditor',
                    'number_of_transactions', 'number_of_cheques'])

        return df

