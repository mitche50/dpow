from datetime import datetime
from http import HTTPStatus
from modules.db import get_db_data, set_db_data, bulk_client_update, bulk_service_update

import MySQLdb
import configparser
import itertools
import json
import logging
import numpy as np
import os
import plotly
import plotly.plotly as py
import plotly.graph_objs as go
import re
import requests
import socket
import time
from flask import Flask, render_template, request, send_from_directory, make_response

logging.basicConfig(handlers=[logging.FileHandler('/var/www/pow/pow.log', 'a', 'utf-8')],
                    level=logging.INFO)

# Read config and parse constants
config = configparser.ConfigParser()
config.read('/var/www/pow/config.ini')

app = Flask(__name__, template_folder='/var/www/pow/templates')

POW_KEY = config.get('webhooks', 'POW_KEY')
AUTHORIZED_IPS = config.get('webhooks', 'ips').split(',')


def auth_check(ip, request_json):
    if ip not in AUTHORIZED_IPS:
        return 'IP Authorization Error', False

    if 'api_key' not in request_json:
        return 'API Key not provided', False

    if request_json['api_key'] != POW_KEY:
        return 'API Key invalid', False

    return '', True


@app.route("/")
@app.route("/index")
def index():

    # Get current POW count
    pow_count_call = "SELECT count(request_id) FROM pow_requests WHERE time_requested >= NOW() - INTERVAL 24 HOUR"
    pow_count_data = get_db_data(pow_count_call)
    pow_count = int(pow_count_data[0][0])

    # Get POW type ratio
    on_demand_count = 0
    precache_count = 0
    pow_ratio_call = ("SELECT pow_type, count(pow_type) FROM pow_requests "
                      "WHERE time_requested >= NOW() - INTERVAL 24 HOUR "
                      "GROUP BY pow_type order by pow_type ASC")
    pow_ratio_data = get_db_data(pow_ratio_call)

    for pow in pow_ratio_data:
        if pow[0] == 'O':
            on_demand_count = pow[1]
        elif pow[0] == 'P':
            precache_count = pow[1]
    if pow_count > 0:
        on_demand_ratio = round((on_demand_count / pow_count) * 100, 1)
        precache_ratio = round((precache_count / pow_count) * 100, 1)
    else:
        on_demand_ratio = 0
        precache_ratio = 0

    # Get service count
    service_count_call = "SELECT count(service_id) FROM service_list"
    service_count_data = get_db_data(service_count_call)
    service_count = int(service_count_data[0][0])

    # Get unlisted / listed services
    unlisted_service_call = "SELECT count(service_id) FROM service_list where service_name is null"
    unlisted_service_data = get_db_data(unlisted_service_call)
    unlisted_services = int(unlisted_service_data[0][0])
    listed_services = service_count - unlisted_services

    # Get client count
    client_count_call = "SELECT count(client_id) FROM client_list"
    client_count_data = get_db_data(client_count_call)
    client_count = int(client_count_data[0][0])

    # Client Ratio
    client_both = 0
    client_urgent = 0
    client_precache = 0
    client_ratio_call = ("SELECT client_type, count(client_type) FROM client_list "
                         "GROUP BY client_type order by client_type ASC")
    client_ratio_data = get_db_data(client_ratio_call)
    if client_count > 0:
        for clients in client_ratio_data:
            if clients[0] == 'P':
                client_precache = int(clients[1])
            elif clients[0] == 'B':
                client_both = int(clients[1])
            elif clients[0] == 'O':
                client_urgent = int(clients[1])

        client_both_ratio = round((client_both / client_count) * 100, 1)
        client_precache_ratio = round((client_precache / client_count) * 100, 1)
        client_urgent_ratio = round((client_urgent / client_count) * 100, 1)
    else:
        client_both_ratio = 0
        client_precache_ratio = 0
        client_urgent_ratio = 0

    # Get 24hr differences
    services_24hr_call = ("SELECT "
                          "(SELECT round(avg(service_count),0) FROM service_connection_log "
                          "WHERE inserted_ts >= NOW() - INTERVAL 1 DAY) - "
                          "(SELECT round(avg(service_count),0) FROM service_connection_log "
                          "WHERE inserted_ts < NOW() - interval 1 DAY and inserted_ts >= NOW() - interval 2 day)")

    services_24hr_data = get_db_data(services_24hr_call)
    services_24hr = services_24hr_data[0][0]
    if services_24hr is None:
        services_24hr = 0

    clients_24hr_call = ("SELECT "
                         "(SELECT round(avg(client_count),0) FROM client_connection_log "
                         "WHERE inserted_ts >= NOW() - INTERVAL 1 DAY) - "
                         "(SELECT round(avg(client_count),0) FROM client_connection_log "
                         "WHERE inserted_ts < NOW() - interval 1 DAY and inserted_ts >= NOW() - interval 2 day)")
    clients_24hr_data = get_db_data(clients_24hr_call)
    clients_24hr = clients_24hr_data[0][0]
    if clients_24hr is None:
        clients_24hr = 0

    work_24hr_call = ("SELECT "
                      "(SELECT count(pow_type) FROM pow_requests WHERE time_requested >= NOW() - INTERVAL 1 DAY) - "
                      "(SELECT count(pow_type) FROM pow_requests WHERE time_requested < NOW() - interval 1 DAY "
                      "and time_requested >= NOW() - interval 2 day)")
    work_24hr_data = get_db_data(work_24hr_call)
    work_24hr = work_24hr_data[0][0]

    # Get info for Services section
    services_call = ("SELECT t1.service_name, t1.service_web, t2.pow FROM "
                     "(SELECT service_id, service_name, service_web FROM service_list) AS t1 "
                     "LEFT JOIN (SELECT service_id, count(service_id) AS pow FROM "
                     "pow_requests group by service_id) AS t2 "
                     "ON t1.service_id = t2.service_id "
                     "WHERE t1.service_name != 'null'"
                     "ORDER BY pow desc")
    services_table = get_db_data(services_call)

    unlisted_services_call = "SELECT count(service_id) FROM service_list where service_name is null"
    unlisted_services_data = get_db_data(unlisted_services_call)
    unlisted_count = unlisted_services_data[0][0]

    unlisted_pow_call = ("SELECT count(request_id) FROM pow_requests WHERE service_id in "
                         "(SELECT service_id FROM service_list WHERE service_name is null)")
    unlisted_pow_data = get_db_data(unlisted_pow_call)
    unlisted_pow = unlisted_pow_data[0][0]

    # Get info for Clients section
    clients_call = ("SELECT t1.client_address, t1. client_type, t2.client_count FROM "
                    "(SELECT client_id, client_address, client_type FROM client_list) as t1 "
                    "LEFT JOIN "
                    "(SELECT client_id, count(client_id) as client_count FROM pow_requests group by client_id) as t2 "
                    "on t1.client_id = t2.client_id order by client_count desc")
    clients_table = get_db_data(clients_call)

    # Get info for POW charts
    hour_p_call = ("SELECT t1.pow_date, t2.pow_type, t2.total FROM "
                   "(SELECT date_format(time_requested, '%Y-%m-%d %H') as pow_date, count(*) as total "
                   "FROM pow_requests "
                   "WHERE date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR "
                   "GROUP BY pow_date order by pow_date asc) as t1 "
                   "LEFT JOIN "
                   "(SELECT date_format( time_requested, '%Y-%m-%d %H') as pow_date, pow_type, count(*) as total "
                   "FROM pow_requests "
                   "WHERE pow_type = 'P' "
                   "AND date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR "
                   "GROUP BY pow_date, pow_type order by pow_date asc) as t2 "
                   "on t1.pow_date = t2.pow_date "
                   "ORDER BY t1.pow_date ASC")
    hour_o_call = ("SELECT t1.pow_date, t2.pow_type, t2.total FROM "
                   "(SELECT date_format( time_requested, '%Y-%m-%d %H') as pow_date, count(*) as total "
                   "FROM pow_requests "
                   "WHERE date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR "
                   "GROUP BY pow_date order by pow_date asc) as t1 "
                   "LEFT JOIN "
                   "(SELECT date_format( time_requested, '%Y-%m-%d %H') as pow_date, pow_type, count(*) as total "
                   "FROM pow_requests WHERE pow_type = 'O' "
                   "AND date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR "
                   "GROUP BY pow_date, pow_type order by pow_date asc) as t2 "
                   "on t1.pow_date = t2.pow_date "
                   "ORDER BY t1.pow_date ASC")
    day_p_call = ("SELECT t1.pow_date, t2.pow_type, t2.total FROM "
                  "(SELECT date_format( time_requested, '%Y-%m-%d' ) as pow_date, count(*) as total "
                  "FROM pow_requests "
                  "WHERE date_format(time_requested, '%Y-%m-%d') >= CURRENT_TIMESTAMP() - INTERVAL 1 MONTH "
                  "GROUP BY pow_date order by pow_date asc) as t1 "
                  "LEFT JOIN "
                  "(SELECT date_format( time_requested, '%Y-%m-%d' ) as pow_date, pow_type, count(*) as total "
                  "FROM pow_requests WHERE pow_type = 'P' "
                  "AND date_format(time_requested, '%Y-%m-%d') >= CURRENT_TIMESTAMP() - INTERVAL 1 MONTH "
                  "GROUP BY pow_date, pow_type order by pow_date asc) as t2 "
                  "on t1.pow_date = t2.pow_date "
                  "ORDER BY t1.pow_date ASC")
    day_o_call = ("SELECT t1.pow_date, t2.pow_type, t2.total FROM "
                  "(SELECT date_format( time_requested, '%Y-%m-%d' ) as pow_date, count(*) as total "
                  "FROM pow_requests "
                  "WHERE date_format(time_requested, '%Y-%m-%d') >= CURRENT_TIMESTAMP() - INTERVAL 1 MONTH "
                  "GROUP BY pow_date order by pow_date asc) as t1 "
                  "LEFT JOIN "
                  "(SELECT date_format( time_requested, '%Y-%m-%d' ) as pow_date, pow_type, count(*) as total "
                  "FROM pow_requests WHERE pow_type = 'O' "
                  "AND date_format(time_requested, '%Y-%m-%d') >= CURRENT_TIMESTAMP() - INTERVAL 1 MONTH "
                  "GROUP BY pow_date, pow_type order by pow_date asc) as t2 "
                  "on t1.pow_date = t2.pow_date "
                  "ORDER BY t1.pow_date ASC")
    minute_p_call = ("SELECT t1.pow_date, t2.pow_type, t2.total FROM "
                     "(SELECT date_format( time_requested, '%Y-%m-%d %H:%i' ) as pow_date, count(*) as total "
                     "FROM pow_requests "
                     "WHERE date_format(time_requested, '%Y-%m-%d %H:%i') >= CURRENT_TIMESTAMP() - INTERVAL 60 MINUTE "
                     "GROUP BY pow_date order by pow_date asc) as t1 "
                     "LEFT JOIN "
                     "(SELECT date_format( time_requested, '%Y-%m-%d %H:%i' ) as pow_date, pow_type, count(*) as total"
                     " FROM pow_requests WHERE pow_type = 'P' "
                     "AND date_format(time_requested, '%Y-%m-%d %H:%i') >= CURRENT_TIMESTAMP() - INTERVAL 60 MINUTE "
                     "GROUP BY pow_date, pow_type order by pow_date asc) as t2 "
                     "on t1.pow_date = t2.pow_date "
                     "ORDER BY t1.pow_date ASC")
    minute_o_call = ("SELECT t1.pow_date, t2.pow_type, t2.total FROM "
                     "(SELECT date_format( time_requested, '%Y-%m-%d %H:%i' ) as pow_date, count(*) as total "
                     "FROM pow_requests "
                     "WHERE date_format(time_requested, '%Y-%m-%d %H:%i') >= CURRENT_TIMESTAMP() - INTERVAL 60 MINUTE "
                     "GROUP BY pow_date order by pow_date asc) as t1 "
                     "LEFT JOIN "
                     "(SELECT date_format( time_requested, '%Y-%m-%d %H:%i' ) as pow_date, pow_type, count(*) as total"
                     " FROM pow_requests WHERE pow_type = 'O' "
                     "AND date_format(time_requested, '%Y-%m-%d %H:%i') >= CURRENT_TIMESTAMP() - INTERVAL 60 MINUTE "
                     "GROUP BY pow_date, pow_type order by pow_date asc) as t2 "    
                     "on t1.pow_date = t2.pow_date "
                     "ORDER BY t1.pow_date ASC")

    pow_day_total_call = ("SELECT date_format( time_requested, '%Y-%m-%d' ), count(*) "
                          "FROM pow_requests "
                          "WHERE date_format(time_requested, '%Y-%m-%d') >= CURRENT_TIMESTAMP() - INTERVAL 1 MONTH "
                          "GROUP BY date_format( time_requested, '%Y-%m-%d' ) "
                          "ORDER BY date_format( time_requested, '%Y-%m-%d' ) ASC")
    pow_hour_total_call = ("SELECT date_format( time_requested, '%Y-%m-%d %H' ), count(*) "
                           "FROM pow_requests "
                           "WHERE date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR "
                           "GROUP BY date_format( time_requested, '%Y-%m-%d %H' ) "
                           "ORDER BY date_format( time_requested, '%Y-%m-%d %H' ) ASC")
    pow_minute_total_call = ("SELECT date_format( time_requested, '%Y-%m-%d %H:%i' ), count(*) "
                             "FROM pow_requests "
                             "WHERE date_format(time_requested, '%Y-%m-%d %H:%i') >= "
                             "CURRENT_TIMESTAMP() - INTERVAL 60 MINUTE "
                             "GROUP BY date_format( time_requested, '%Y-%m-%d %H:%i' ) "
                             "ORDER BY date_format( time_requested, '%Y-%m-%d %H:%i' ) ASC")
    avg_time_call = ("SELECT date_format( time_requested, '%Y-%m-%d %H' ), pow_type, "
                     "avg(timediff(time_responded, time_requested)) "
                     "FROM pow_requests "
                     "WHERE date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR "
                     " GROUP BY date_format( time_requested, '%Y-%m-%d %H' ), pow_type")
    avg_combined_call = ("SELECT date_format( time_requested, '%Y-%m-%d %H' ), "
                         "avg(timediff(time_responded, time_requested)) "
                         "FROM pow_requests "
                         "WHERE date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR "
                         "GROUP BY date_format( time_requested, '%Y-%m-%d %H' )")
    avg_overall_call = ("SELECT avg(timediff(time_responded, time_requested)) FROM pow_requests "
                        "WHERE date_format(time_requested, '%Y-%m-%d %H') >= CURRENT_TIMESTAMP() - INTERVAL 24 HOUR")
    avg_difficulty_call = ("SELECT avg(pow_difficulty) FROM pow_requests "
                           "WHERE time_requested >= NOW() - INTERVAL 30 MINUTE")
    avg_requests_call = ("SELECT date_format( time_requested, '%Y-%m-%d' ), count(request_id) FROM pow_requests "
                         "WHERE time_requested >= NOW() - INTERVAL 1 MONTH "
                         "GROUP BY date_format( time_requested, '%Y-%m-%d' )")

    day_total = get_db_data(pow_day_total_call)
    hour_total = get_db_data(pow_hour_total_call)
    minute_total = get_db_data(pow_minute_total_call)

    day_precache = get_db_data(day_p_call)
    day_ondemand = get_db_data(day_o_call)
    hour_precache = get_db_data(hour_p_call)
    hour_ondemand = get_db_data(hour_o_call)
    minute_precache = get_db_data(minute_p_call)
    minute_ondemand = get_db_data(minute_o_call)

    avg_response = get_db_data(avg_time_call)
    avg_combined_time = get_db_data(avg_combined_call)
    avg_overall_data = get_db_data(avg_overall_call)
    avg_requests_data = get_db_data(avg_requests_call)
    total_requests = 0
    count_requests = 0

    for row in avg_requests_data:
        total_requests += row[1]
        count_requests += 1

    requests_avg = int(total_requests / count_requests)

    if avg_overall_data[0][0] is not None:
        avg_overall = round(float(avg_overall_data[0][0]), 1)
    else:
        avg_overall = 0

    avg_difficulty_data = get_db_data(avg_difficulty_call)
    if avg_difficulty_data[0][0] is not None:
        avg_difficulty = round(avg_difficulty_data[0][0], 1)
    else:
        avg_difficulty = 1.0

    return render_template('index.html', pow_count=pow_count, on_demand_ratio=on_demand_ratio,
                           precache_ratio=precache_ratio, service_count=service_count, client_count=client_count,
                           client_both_ratio=client_both_ratio, client_precache_ratio=client_precache_ratio,
                           client_urgent_ratio=client_urgent_ratio, listed_services=listed_services,
                           unlisted_services=unlisted_services, services_24hr=services_24hr, clients_24hr=clients_24hr,
                           work_24hr=work_24hr, services_table=services_table, unlisted_count=unlisted_count,
                           unlisted_pow=unlisted_pow, clients_table=clients_table, day_total=day_total,
                           hour_total=hour_total, minute_total=minute_total, day_ondemand=day_ondemand,
                           day_precache=day_precache, hour_ondemand=hour_ondemand, hour_precache=hour_precache,
                           minute_ondemand=minute_ondemand, minute_precache=minute_precache, avg_response=avg_response,
                           avg_overall=avg_overall, avg_combined_time=avg_combined_time, avg_difficulty=avg_difficulty,
                           requests_avg=requests_avg)


@app.route('/pow_update', methods=["POST"])
def pow_update():
    request_json = request.get_json()
    ip = request.remote_addr

    error_msg, auth = auth_check(ip, request_json)

    if auth is False:
        logging.info("{}: {} made a bad POST request to POW Update: {}".format(datetime.now(), ip, error_msg))
        return error_msg, HTTPStatus.BAD_REQUEST

    if auth is True:
        time_requested = datetime.strptime(request_json['time_requested'], "%Y-%m-%d %H:%M:%S.%f")
        time_responded = datetime.strptime(request_json['time_responded'], "%Y-%m-%d %H:%M:%S.%f")
        pow_call = ("INSERT INTO pow_requests (request_id, service_id, client_id, pow_type, pow_difficulty, "
                    "time_requested, time_responded) "
                    "VALUES ('{}', '{}', '{}', '{}', {}, '{}', '{}')".format(request_json['request_id'],
                                                                             request_json['service_id'],
                                                                             request_json['client_id'],
                                                                             request_json['pow_type'],
                                                                             request_json['pow_difficulty'],
                                                                             time_requested,
                                                                             time_responded))
        set_db_data(pow_call)
        return 'POW Inserted', HTTPStatus.OK


@app.route('/client_update', methods=["POST"])
def update_client():
    request_json = request.get_json()
    ip = request.remote_addr

    error_msg, auth = auth_check(ip, request_json)

    if auth is False:
        logging.info("{}: {} made a bad POST request to Client Update: {}".format(datetime.now(), ip, error_msg))
        return error_msg, HTTPStatus.BAD_REQUEST

    if auth is True:
        client_list = request_json['clients']

        if len(client_list) == 0:
            delete_client_table = "DELETE FROM client_list"
            set_db_data(delete_client_table)
            return 'Clients Updated', HTTPStatus.OK

        for client in client_list:
            if client['client_type'].upper() not in ['B', 'P', 'O']:
                return 'Invalid client_type for client_id: {}'.format(client['client_id']), HTTPStatus.BAD_REQUEST
        bulk_client_update(client_list)
        client_log_call = ("INSERT INTO client_connection_log (client_count) VALUES ({})".format(len(client_list)))
        set_db_data(client_log_call)
        return 'Clients Updated', HTTPStatus.OK

    return 'No action taken', HTTPStatus.OK


@app.route('/service_update', methods=["POST"])
def update_services():
    request_json = request.get_json()
    ip = request.remote_addr

    error_msg, auth = auth_check(ip, request_json)

    if auth is False:
        logging.info("{}: {} made a bad POST request to Service Update: {}".format(datetime.now(), ip, error_msg))
        return error_msg, HTTPStatus.BAD_REQUEST

    if auth is True:
        services_list = request_json['services']
        bulk_service_update(services_list)
        service_log_call = ("INSERT INTO service_connection_log (service_count) VALUES ({})".format(len(services_list)))
        set_db_data(service_log_call)
        return 'Services Updated', HTTPStatus.OK

    return 'No action taken', HTTPStatus.OK


if __name__ == "__main__":
    app.run()
