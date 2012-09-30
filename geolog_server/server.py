# Copyright 2012 Timur Evdokimov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from datetime import datetime
import errno
import functools
import json
import socket
import logging
from string import split
from bson.objectid import ObjectId
from pymongo.cursor import Cursor
import time
from tornado import ioloop, iostream, web

#
# Database connection properties. Set MONGODB_HOST to None to disable database
#
from tornado.web import RequestHandler

MONGODB_HOST = "localhost" # None to disable database connection
MONGODB_PORT = 27017
MONGODB_DB = 'geolog'

from pymongo import Connection

class GeologServer:

    db = Connection(MONGODB_HOST, MONGODB_PORT)[MONGODB_DB]

    def connection_ready(self, sock, fd, events):
        while True:
            try:
                connection, address = sock.accept()
            except socket.error, e:
                if e[0] not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.ECONNRESET):
                    raise
                return
            connection.setblocking(0)
            stream = iostream.IOStream(connection)
            stream.read_until_close(self.on_body)

    # sensor submits data as degrees/minutes/seconds
    def convert_to_degrees(self, value):
        v = float(value) / 100
        value_degrees = int(v * 100)/100
        degrees_ = value_degrees + float(v - value_degrees) / 60 * 100
        return degrees_


    def parse_tk103b(self, data):
        # incoming data may contain
        # ##,imei:012497000326409,A;##,imei:012497000326409,A;##,imei:012497000326409,A;##,imei:012497000326409,A;
        # imei:012497000326409,tracker,1207231727,0031645890190,F,092716.000,A,5221.7102,N,00457.7187,E,0.00,,;##,imei:012497000326409,A;##,imei:012497000326409,A;##,imei:012497000326409,A;##,imei:012497000326409,A;
        # ##,imei:012497000326409,A;##,imei:012497000326409,A;##,imei:012497000326409,A; imei:012497000326409,tracker,1207231729,0031645890190,F,092944.000,A,5221.7102,N,00457.7187,E,0.00,,;##,imei:012497000326409,A;


        if not "imei" in data:
            return ()

        if not ";" in data:
            return ()

        result = []

        for row in data.split(";"):
            if row.startswith("##,"):
                row = row[3:]
            fields = row.split(",")

            imei = fields[0][5:]
            if len(fields) > 1:
                if len(fields) == 2:
                    if fields[1] == "A":
                        result.append((imei,"OK"))
                    else:
                        result.append((imei,fields[1]))

                elif fields[1] == "tracker":
                    #       0                  1      2            3        4   5        6  7         8     9     10 11   12
                    # imei:012497000326409,tracker,1207222134,0031645890190,F,133455.000,A,5222.0177,N,00454.4011,E,4.16,218.50,

                    # 2 - date
                    # 3 - admin phone
                    # 4 - terminator F
                    # 5 - ??
                    # 6 - terminator A
                    # 7 - latitude
                    latitude = self.convert_to_degrees(float(fields[7] if fields[8] == "N" else -fields[7]))
                    # 8 - N/S hemisphere
                    # 9 - longtitude
                    longtitude = self.convert_to_degrees(float(fields[9] if fields[10] == "E" else -fields[9]))
                    # 10 - W/E hemisphere
                    # 11 - speed, knots
                    speed = float(fields[11]) * 1.852
                    # 13 - bearing, grad
                    bearing = 0 if len(fields[12]) == 0 else float(fields[12])

                    result.append( (imei, "POS", latitude, longtitude, speed, bearing) )
        return result

    def record_position(self, imei, latitude, longtitude, speed, bearing):
        global last_positions, position_history
        logging.info("%s at position: %s/%s %s, %s" % (imei, latitude, longtitude, speed, bearing) )

        try:
            last_positions
        except NameError:
            last_positions = self.db.last_positions
            position_history = self.db.position_history

        last_position = last_positions.find_one({"_id": imei})

        if speed == 0 and last_position and last_position['speed'] == 0:
            logging.info("Position not changed")
        else:
            position_history.insert({
                    "imei": imei,
                    "created": datetime.now(),
                    "latitude": latitude,
                    "longtitude": longtitude,
                    "speed": speed,
                    "bearing": bearing})

        last_positions.update(spec={"_id": imei}, document={
                    "_id": imei,
                    "last_seen": datetime.now(),
                    "latitude": latitude,
                    "longtitude": longtitude,
                    "speed": speed,
                    "bearing": bearing
                }, upsert=True)

    def on_body(self, data):
        logging.info("%s - %s" % (datetime.today(), data))

        parsed_data = self.parse_tk103b(data)
        for chunk in parsed_data:
            if chunk == ():
                logging.info("Not recognized as data")
            elif len(chunk) == 2:
                logging.info("Status message: %s" % chunk[1] )
            elif len(chunk) == 6:
                self.record_position(chunk[0], chunk[2], chunk[3], chunk[4], chunk[5])

def parse_iso_datetime(str) :
            # parse a datetime generated by datetime.isoformat()
    try :
        return datetime.fromtimestamp(time.mktime(time.strptime(str, "%Y-%m-%dT%H:%M:%S")))
    except ValueError :
        return datetime.fromtimestamp(time.mktime(time.strptime(str, "%Y-%m-%dT%H:%M:%S.%f")))

def json_serializer(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    elif isinstance(obj, time.struct_time):
        return "?"
    elif isinstance(obj, ObjectId):
        return obj.__str__()
    elif isinstance(obj, Cursor):
        return [result for result in obj]
    else:
        raise TypeError, 'Object of type %s with value of %s is not JSON serializable' % (type(obj), repr(obj))

def json_dump(obj):
    return json.dumps(obj,indent=1,default=json_serializer, ensure_ascii=False)

class JSONHandler(RequestHandler):

    db = Connection(MONGODB_HOST, MONGODB_PORT)[MONGODB_DB]



    def send_response(self, obj):
        try:
            self.write(json_dump(obj))
        except Exception, e:
            logging.error(e)
            self.write(e.message)

    def get(self, *args, **kwargs):
        try:
            uriData = split(self.request.uri[1:], "/")
            entity = uriData[0]
            if entity == "imei":
                imei = uriData[1]
                last_positions = self.db.last_positions
                imei_last_position = last_positions.find_one({"_id": imei})
                self.send_response(imei_last_position)
            elif entity == "trip":
                imei = uriData[1]
                if len(uriData) > 2:
                    (date_from, date_to) = (parse_iso_datetime(uriData[2]), parse_iso_datetime(uriData[3]))
                else:
                    (date_from, date_to) = (None, None)

                position_history = self.db.position_history
                if date_from and date_to:
                    self.send_response(position_history.find({ 'imei' : imei,
                                                               'created': {'$gte': date_from,'$lt': date_to}}).sort([('created', 1)]))

                else:

                    all_positions = position_history.find({'imei': imei}).sort([('created', 1)])

                    trips = [{'imei' : imei}]
                    current_trip = None
                    previous = None
                    points = 0
                    for p in all_positions:

                        if not current_trip:
                            current_trip = {'trip_start' : p['created'], 'trip_finish' : p['created'] }
                        else:
                            current_trip['trip_finish'] = p['created']

                        if previous:
                            delta = p['created'] - previous['created']
                            if delta.seconds > 3600:
                                current_trip['trip_finish'] = previous['created']
                                current_trip['points'] = points
                                trips.append(current_trip)
                                points = 0
                                current_trip = {'trip_start' : p['created'], 'trip_finish' : p['created'] }

                        previous = p
                        points += 1

                    current_trip['points'] = points
                    trips.append(current_trip)

                    self.send_response(trips)

        except Exception, e:
            logging.error(e)
            self.write(e.message)
            self.write(e)



if __name__ == '__main__':
    LOG_FILENAME = '/opt/web/geolog/log/server.log'
    logging.basicConfig(format='%(asctime)-15s %(message)s', level=logging.INFO, filename=LOG_FILENAME)

    # sensor listener
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(0)
    sock.bind(("", 9000))
    sock.listen(5000)
    server = GeologServer()

    io_loop = ioloop.IOLoop.instance()
    callback = functools.partial(server.connection_ready, sock)
    io_loop.add_handler(sock.fileno(), callback, io_loop.READ)

    # json endpoint
    application = web.Application([
        (r"^/.*", JSONHandler),
    ])
    application.listen(9001)

    try:
        io_loop.start()
    except KeyboardInterrupt:
        io_loop.stop()
        print "exited cleanly"

