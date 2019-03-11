from datetime import datetime

import MySQLdb
import configparser
import logging

logging.basicConfig(handlers=[logging.FileHandler('/var/www/pow/pow.log', 'a', 'utf-8')],
                    level=logging.INFO)

# Read config and parse constants
config = configparser.ConfigParser()
config.read('/var/www/pow/config.ini')

# DB connection settings
DB_HOST = config.get('webhooks', 'host')
DB_USER = config.get('webhooks', 'user')
DB_PW = config.get('webhooks', 'password')
DB_SCHEMA = config.get('webhooks', 'schema')
DB_PORT = config.get('webhooks', 'db_port')


def get_db_data(db_call):
    """
    Retrieve data from DB
    """
    db = MySQLdb.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER, passwd=DB_PW, db=DB_SCHEMA, use_unicode=True,
                         charset="utf8")
    db_cursor = db.cursor()
    db_cursor.execute(db_call)
    db_data = db_cursor.fetchall()
    db_cursor.close()
    db.close()
    return db_data


def set_db_data(db_call):
    """
    Enter data into DB
    """
    db = MySQLdb.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER, passwd=DB_PW, db=DB_SCHEMA, use_unicode=True,
                         charset="utf8")
    db_cursor = db.cursor()

    try:
        db_cursor.execute(db_call)
        db.commit()
        db_cursor.close()
        db.close()
    except MySQLdb.ProgrammingError as e:
        logging.info("{}: Exception entering data into database".format(datetime.now()))
        logging.info("{}: {}".format(datetime.now(), e))
        db_cursor.close()
        db.close()
        raise e


def bulk_client_update(clients):
    """
    Provide a bulk insert for the client list
    """
    # First, delete all the clients in the table
    delete_client_table = "DELETE FROM client_list"
    set_db_data(delete_client_table)

    # Next, reset auto increment to 1
    auto_call = "ALTER TABLE client_list AUTO_INCREMENT = 1"
    set_db_data(auto_call)

    # Then, update the client table with all provided clients
    create_row_call = ("INSERT INTO client_list (client_id, client_address, client_type, "
                       "client_demand_count, client_precache_count) VALUES ")
    try:
        for index, client in enumerate(clients):
            if index == 0:
                create_row_call = create_row_call + ("('{}', '{}', '{}', {}, {})".format(client['client_id'],
                                                                                         client['client_address'],
                                                                                         client['client_type'].upper(),
                                                                                         client['client_demand_count'],
                                                                                         client['client_precache_count']
                                                                                         )
                                                     )
            else:
                create_row_call = create_row_call + (" , ('{}', '{}', '{}', {}, {})".format(client['client_id'],
                                                                                            client['client_address'],
                                                                                            client['client_type'].upper(),
                                                                                            client['client_demand_count'],
                                                                                            client['client_precache_count']
                                                                                            )
                                                     )

        set_db_data(create_row_call)
    except Exception as e:
        logging.info("{}: Exception inserting clients into database".format(datetime.now()))
        logging.info("{}: {}".format(datetime.now(), e))
        raise e

    logging.info("Clients set successfully in DB.")


def bulk_service_update(services):
    """
    Provide a bulk insert for the service list
    """
    # First, delete all the clients in the table
    delete_service_table = "DELETE FROM service_list"
    set_db_data(delete_service_table)

    # Then, update the client table with all provided clients
    create_row_call = "INSERT INTO service_list (service_id, service_name, service_web) VALUES "
    try:
        for index, service in enumerate(services):
            if service['service_id'] is not None:
                id = service['service_id'].replace("'", "''")
            else:
                id = service['service_id']
            if service['service_name'] is not None:
                name = service['service_name'].replace("'", "''")
            else:
                name = service['service_name']
            if service['service_web'] is not None:
                web = service['service_web'].replace("'", "''")
            else:
                web = service['service_web']

            if index == 0:
                if (name == 'null' and web != 'null') or (name is None and web is not None):
                    create_row_call = create_row_call + ("('{}', Null, '{}')".format(id, web))
                elif (name == 'null' and web == 'null') or (name is None and web is None):
                    create_row_call = create_row_call + ("('{}', Null, Null)".format(id))
                elif name != 'null' and web == 'null' or (name is not None and web is None):
                    create_row_call = create_row_call + ("('{}', '{}', Null)".format(id, name))
                else:
                    create_row_call = create_row_call + ("('{}', '{}', '{}')".format(id, name, web))
            else:
                if (name == 'null' and web != 'null') or (name is None and web is not None):
                    create_row_call = create_row_call + (", ('{}', Null, '{}')".format(id, web))
                elif (name == 'null' and web == 'null') or (name is None and web is None):
                    create_row_call = create_row_call + (", ('{}', Null, Null)".format(id))
                elif (name != 'null' and web == 'null') or (name is not None and web is None):
                    create_row_call = create_row_call + (", ('{}', '{}', Null)".format(id, name))
                else:
                    create_row_call = create_row_call + (", ('{}', '{}', '{}')".format(id, name, web))

        set_db_data(create_row_call)
    except Exception as e:
        logging.info("{}: Exception inserting services into database".format(datetime.now()))
        logging.info("{}: {}".format(datetime.now(), e))
        raise e

    logging.info("Services set successfully in DB.")