Lets write a small expense manager in Python

Implementation guidelines, API and Library usage
sqlite3 as database
sqlalchemy as ORM
pandas for reading, manipulating csv data
click for parsing command line arguments and invoke respective commands
API from pandas or sqlalchemy which helps to commit a pandas dataframe into the database shall be used for brevity
Use pandas pipe operations wherever possible for brevity
Use alembic for database migrations

SQL design
Tables and their columns 
accounts
primary key, auto incrementing
IBAN, of type string, shall be unique
name, of type string
bank, of type string
credit_categories
primary key, auto incrementing 
category, of type string, shall be unique 
debit_categories
primary key, auto incrementing
category, of type string, shall be unique 
credits
primary key, auto incrementing 
hash, of type string, shall be unique 
description, of type string, shall be unique
date, of type date
amount, of type decimal
debits
primary key, auto incrementing
hash, of type string, shall be unique 
description, of type string, shall be unique
date, of type date
amount, of type decimal
credit_classification
primary key, auto incrementing
credit, a foreign key to credits table, shall be unique
credit_category, a foreign key to credit_categories
debit_classification
primary key, auto incrementing 
debit, a foreign key to debits, shall be unique
debit_category, a foreign key to debit_categories
credit_annotation
primary key, auto incrementing
annotation, of type string
credit, a foreign key to credits table, shall be unique
debit_annotation
primary key, auto incrementing
annotation, of type string
debit_category, a foreign key to debit_categories
parent_credits same as credit
parent_debits same as debit
credit_parent_child_mapping
primary key, auto incrementing
child_credit, a foreign key to credit
parent_credit, a foreign key to parent credit
debit_parent_child_mapping
primary key, auto incrementing
child_credit, a foreign key to debit
parent_credit, a foreign key to parent debit
A static lookup table, expense_recurrence_type
primary key, auto incrementing
recurrence_type, of type string. Statically populated with m, w, d, y
expense_recurrence
primary key, auto incrementing
debit_category, a foreign key to debit_categories
recurrence_type, a foreign key to expense_recurrence_type
recurrence_frequency, of type integer
budgets
primary key, auto incrementing
debit_category, a foreign key to debit_categories
recurrence, a foreign key to expense_recurrence
limit, of type decimal
virtual_accounts
primary key, auto incrementing
IBAN, of type string, shall be unique
name, of type string
parent, foreign key to accounts

The functions required are
init
Input
kohle_rc_path, of type path. Path to the configuration file. It shall contain a default text editor for input, color formats for console output, initial expense recurrence types and is extendable to other configurations. 
text_editor, of type path. Path to the text editor to be invoked
Preconditions
kohle.toml shall be of type toml
Actions
Open kohle_rc_path file in text_editor. The user fills and saves the file
It shall initialize create database and tables
Errors
Throws if kohle_rc_path is not readable or writable
Throws if text_editor is not found in the path
Throws if kohle_rc_path is not toml file
import_statement
Input
statement_path, of type path, csv statement file path
account_name, of type string, the name of the account for which the import is done
Preconditions
The input csv shall contain columns date, description, credit and debit
Actions
It shall parse the file into rows and later insert them into the tables credits and debits. Note that credit and debit are in the same table of csv. We might have to group them and later insert into respective tables. 
Additionally compute a sha256 hash of description which shall be the hash in the tables, this shall help to know if a transaction is already part of the credit or debit table
Before insertion check if the transactions were already imported based on the hashes, if yes throw a warning and skip import for those transactions with hash collision, write only new rows into the tables. Use pandas read_csv and sqlalchemy apis to create dataframes, check hash collision, and commit to db 
Errors
Throws if statement_path is not readable
Throws if csv is not as per preconditions
add_credit_category
Inputs
The function shall take a string as input
Actions
It shall add a new credit category
Check edit distance with existing category
If category already exists, ignore addition of the category
Implementation Repetition
Similarly there shall function add_debit_category which shall do the same for debits
no_category_debits
Input: None
Actions
It shall retrieve all transactions which do not have a category debit_classification table. 
It shall then display it in the console with id, description, annotation, amount. 
Implementation Repetition
Similarly there shall function no_category_credits which shall do the same for credits
categorise_debit
Inputs
Click function shall take two arguments: primary key id of the transaction and category string. 
Actions
It shall set a category for a given transaction, by adding relationship between category and transaction to the debit classification table. 
Errors
Let's add a check if the category is already present. 
If the user provided category is not present in the list of existing debit categories, the category to transaction mapping entry shall not be inserted into the respective category but an error shall be thrown that category is not shown. 
Implementation Repetition
Similarly there shall be a function to do these actions for credits
annotate_credit
Inputs
key, of type integer, the primary key id of the transaction to be annotated
annotation, of type string
Actions
Adds a credit to annotation relationship in credit_annotation table
Errors
Throws if key is not present in the credit table
Implementation Repetition
Similarly there shall be a function to do these actions for debits
chunk_debit
Inputs
id, of type integer, primary key to debit transactions which has to be broken into multiple transactions
Preconditions
kohle.toml shall have text editor configured
Actions
The original transaction shall be “moved” to the debit_master
The new chunked transaction shall be committed to the debits table. This shall be similar to the interactive rebase of a git command. If the chunk command is invoked, the user shall be prompted to enter the chunk details in a temporary file opened in the console by firing up a text editor configured in kohle.toml
The user shall now enter the chunks in the following format in the temporary file shown by us. Each line shall contain a chunk detail. The line shall have space separated entries of amount, description. These details are added to credits table along with parent child mapping
Errors
Throws if kohle.toml has no text editor configured
Throws if the sum of all amounts shall not match the actual parent amount
Implementation Repetition
Repeat also for the credit table.
display_monthly_balance
Inputs
month, of type string
Actions
Shall display the monthly credits and debits along with the final balance. Final balance shall be difference between sum of all credits and sum of all debits
Errors
Throws if month is invalid
monthly_statement
Inputs
month, of type string
Actions
Shall display all transactions sorted by date for a given month, both credits and debits. 
While displaying each row shall contain date, annotation, amount, a hint if it was credit or debit, credit or debit category which has been mapped to the transaction in the credit classification or debit classification table
If the category for the credit or debit is not available print a star for now in the place of category
While printing statements if the current transaction has a parent in the child to parent mapping table, then print the parent in the next line after the current transaction with 1 tab indentation
Errors
Throws if month is invalid
monthly_statement_by_category
Inputs
month, of type string
Actions
Shall produce a category wise debit summary for a given month and show the amount spent per category for the month. 
If there are transaction with no categories mapped to in the debit classification table then accumulate all the transaction amount and in the output displayed add a final row with category uncategorized and the accumulated amount of uncategorized transactions
Errors
Throws if month is invalid
add_expense_limit
Inputs
expense category, of type string 
unit, of type string, denotes the frequency type. Should be from the choices - d, w, m, y representing day, week, month, year
frequency, of type integer
limit, of type decimal, amount cap for the expense category
Actions
We store the expense category, recurrence type, frequency and the limit in the budgets table
Errors
Throws if the category has already a  limit
Throws if the category is not in the category table 
Throws if frequency type is invalid 
budget_summary
Inputs
unit, of type string. The unit at which the budget limits have to displayed, it can either “m” or “y”
Actions
It shall display limits per category in a given frequency time unit, sorted alphabetically.
The budget limits will have to be scaled according to the time unit.
delete_credit_category
Inputs
name, of type string, name of the category
Actions
Lookup for the category in the credit_category table, delete it, and also adjust the foreign key references in the credits, parent_credits, budgets, expense_recurrence tables
Warn if the given category is not found
Implementation Repetition
Similarly there shall be a function to do these actions for debits
delete_credit_transaction
Inputs
id, of type integer, the primary key to the transaction to be deleted
Actions
Lookup the credit transaction in the credit table and remove it. Adjust all tables which use credit as a foreign key
Warn if given id is not found
Implementation Repetition
Similarly there shall be a function to do these actions for debits
delete_expense_limit
Inputs
category, of type string, category for which the limits have to be deleted
Actions
Remove the limits and recurrence data for the category
modify_expense_limit
Inputs
category, of type string, category for which the limits have to be modified
limit, of type decimal, amount cap for the expense category
Actions
Modify the limits and recurrence data for the category
modify_credit_category
Inputs
category, of type string, category for which the limits have to be modified
Actions
Modify the name of the category
Implementation Repetition
Similarly there shall be a function to do these actions for debits
add_virtual account
Inputs
bank_name, of type string, name of the bank in which account is held
mark_as_transfer
Inputs

Savings plan
Calculate stock and fund value
Debts

