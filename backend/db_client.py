import mysql.connector
from mysql.connector import errorcode
import datetime
import hvac
import base64

customer_table = '''
CREATE TABLE IF NOT EXISTS `customers` (
    `cust_no` int(11) NOT NULL AUTO_INCREMENT,
    `birth_date` varchar(255) NOT NULL,
    `first_name` varchar(255) NOT NULL,
    `last_name` varchar(255) NOT NULL,
    `create_date` varchar(255) NOT NULL,
    `social_security_number` varchar(255) NOT NULL,
    `address` varchar(255) NOT NULL,
    `salary` varchar(255) NOT NULL,
    PRIMARY KEY (`cust_no`)
) ENGINE=InnoDB;'''

class DbClient:
    conn = None
    vault_client = None
    key_name = None
    mount_point = None

    def __init__(self, uri, prt, uname, pw, db):
        self.init_db(uri, prt, uname, pw, db)

    def init_db(self, uri, prt, uname, pw, db):
        self.uri = uri
        self.port = prt
        self.username = uname
        self.password = pw
        self.db = db
        self.connect_db(uri, prt, uname, pw)
        cursor = self.conn.cursor()
        print("Preparing database {}...".format(db))
        cursor.execute('CREATE DATABASE IF NOT EXISTS `{}`'.format(db))
        cursor.execute('USE `{}`'.format(db))
        print("Preparing customer table...")
        cursor.execute(customer_table)
        self.conn.commit()
        cursor.close()

    # Later we will check to see if this is None to see whether to use Vault or not
    def init_vault(self, addr, token, path, key_name):
        if not addr or not token:
            return
        else:
            print("Connecting to vault server: {}".format(addr))
            self.vault_client = hvac.Client(url=addr, token=token)
            self.key_name = key_name
            self.mount_point = path

    # the data must be base64ed before being passed to encrypt
    def encrypt(self, value):
        try:
            response = self.vault_client.secrets.transit.encrypt_data(
                mount_point = self.mount_point,
                name = self.key_name,
                plaintext = base64.b64encode(value.encode()).decode('ascii')
            )
            print(response)
            return response['data']['ciphertext']
        except Exception as e:
            print('There was an error encrypting the data: {}'.format(e))

    # The data returned from Transit is base64 encoded so we decode it before returning
    def decrypt(self, value):
        # support unencrypted messages on first read
        #print('Decrypting {}'.format(value))
        if not value.startswith('vault:v'):
            return value
        else: 
            try:
                response = self.vault_client.secrets.transit.decrypt_data(
                    mount_point = self.mount_point,
                    name = self.key_name,
                    ciphertext = value
                )
                print(response)
                plaintext = response['data']['plaintext']
                print(plaintext)
                decoded = base64.b64decode(plaintext).decode()
                print(decoded)
                return decoded
            except Exception as e:
                print('There was an error encrypting the data: {}'.format(e))
    
    # Long running apps may expire the DB connection
    def _execute_sql(self,sql,cursor):
        try:
            cursor.execute(sql)
            return 1
        except mysql.connector.errors.OperationalError as e:            
            if e[0] == 2006:
                print('Error encountered: {}.  Reconnecting db...'.format(e))
                self.init_db(self.uri, self.port, self.username, self.password, self.db)
                cursor = self.conn.cursor()
                cursor.execute(sql)
                return 0

    def connect_db(self, uri, prt, uname, pw):
        print('Connecting to {} with username {} and password {}'.format(uri, uname, pw))
        try:
            self.conn = mysql.connector.connect(user=uname, password=pw, host=uri, port=prt)
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                print("Something is wrong with your user name or password")
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                print("Database does not exist")
            else:
                print(err)

    def get_customer_records(self, num = None):
        if num is None:
            num = 10
        statement = 'SELECT * FROM `customers` LIMIT {}'.format(num)
        cursor = self.conn.cursor()
        self._execute_sql(statement, cursor)
        results = []
        for row in cursor:
            try:
                r = {}
                r['customer_number'] = row[0]
                r['birth_date'] = row[1]
                r['first_name'] = row[2]
                r['last_name'] = row[3]
                r['create_date'] = row[4]
                r['ssn'] = row[5]
                r['address'] = row[6]
                r['salary'] = row[7]
                if self.vault_client is not None:
                    r['birth_date'] = self.decrypt(r['birth_date'])
                    r['ssn'] = self.decrypt(r['ssn'])
                    r['address'] = self.decrypt(r['address'])
                    r['salary'] = self.decrypt(r['salary'])
                results.append(r)
            except Exception as e:
                print('There was an error retrieving the record: {}'.format(e))
        return results

    def insert_customer_record(self, record):
        if self.vault_client is None:
            statement = '''INSERT INTO `customers` (`birth_date`, `first_name`, `last_name`, `create_date`, `social_security_number`, `address`, `salary`) 
                            VALUES  ("{}", "{}", "{}", "{}", "{}", "{}", "{}");'''.format(record['birth_date'], record['first_name'], record['last_name'], record['create_date'], record['ssn'], record['address'], record['salary'] )
        else:
            statement = '''INSERT INTO `customers` (`birth_date`, `first_name`, `last_name`, `create_date`, `social_security_number`, `address`, `salary`) 
                            VALUES  ("{}", "{}", "{}", "{}", "{}", "{}", "{}");'''.format(self.encrypt(record['birth_date']), record['first_name'], record['last_name'], record['create_date'], self.encrypt(record['ssn']), self.encrypt(record['address']), self.encrypt(record['salary']) )
        print(statement)
        cursor = self.conn.cursor()
        self._execute_sql(statement, cursor)
        self.conn.commit()
        return self.get_customer_records()

    def update_customer_record(self, record):
        if self.vault_client is None:
            statement = '''UPDATE `customers`  
                       SET birth_date = "{}", first_name = "{}", last_name = "{}", social_security_number = "{}", address = "{}", salary = "{}"
                       WHERE cust_no = {};'''.format(record['birth_date'], record['first_name'], record['last_name'], record['ssn'], record['address'], record['salary'], record['cust_no'] )
        else:
            statement = '''UPDATE `customers`  
                       SET birth_date = "{}", first_name = "{}", last_name = "{}", social_security_number = "{}", address = "{}", salary = "{}"
                       WHERE cust_no = {};'''.format(self.encrypt(record['birth_date']), record['first_name'], record['last_name'], self.encrypt(record['ssn']), self.encrypt(record['address']), self.encrypt(record['salary']), record['cust_no'] )
        print(statement)
        cursor = self.conn.cursor()
        self._execute_sql(statement, cursor)
        self.conn.commit()
        return self.get_customer_records()