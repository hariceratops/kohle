import re
import hashlib
import pandas as pd
import click
from sqlalchemy import DateTime, String, Column, Integer
from sqlalchemy import Table
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase



class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transaction"

    id = Column(String, primary_key=True)
    narration = Column(String)
    amount = Column(Integer)
    transaction_type = Column(String)
    date_time = Column(DateTime)


class Amount(Base):
    __tablename__ = "accounts"


    id = Column(Integer, primary_key=True)
    account_number = Column(Integer)
    currency = Column(String)


pattern_jahresbeitrag = r""
patern_sepa_salary = r""
pattern_cash_withdrawal = r""
pattern_sepa_credit_transfer = r""
pattern_debit_card_payment = r""
pattern_sepa_direct_debit = r""
pattern_kontoabschluss = r""
pattern_sepa_direct_debit_elv = r""


def print_df(df):
    print(df)
    return df


def print_groupby(groups):
    for _, values in groups:
        print(values)

    return groups


def clean_groups(groups):
    pass


@click.group()
def cli():
    pass


@cli.command()
@click.argument('csv_file')
def import_statement(csv_file):
    df = pd.read_csv(csv_file, header=4, sep=';', encoding='ISO-8859-1') \
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
            .pipe(lambda df: 
                  df.assign(description = df.apply(
                      lambda row: f"{row['beneficiary']}/{row['details']}/{row['iban']}", axis=1
              ))) \
            .pipe(lambda df: df.assign(transaction_hash = df.apply(lambda row: hashlib.sha256(row['description'].encode('utf-8')).hexdigest(), axis=1))) \
            .drop(columns=[
                'beneficiary', 'details', 'iban', 'booking_date', 'value_date',
                'bic', 'customer_reference', 'mandate_reference', 'creditor_id',
                'compensation_amount', 'original_amount', 'ultimate_creditor',
                'number_of_transactions', 'number_of_cheques']) \
            .groupby(by="transaction_type") \
            .pipe(lambda groups: print_groupby(groups))


    engine = create_engine('sqlite://', echo=True)
    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    cli()


