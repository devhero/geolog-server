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
import socket
import logging
from tornado import ioloop, iostream

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
            stream.read_until_close(on_body)

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
                    latitude = convert_to_degrees(float(fields[7] if fields[8] == "N" else -fields[7]))
                    # 8 - N/S hemisphere
                    # 9 - longtitude
                    longtitude = convert_to_degrees(float(fields[9] if fields[10] == "E" else -fields[9]))
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

        parsed_data = parse_tk103b(data)
        for chunk in parsed_data:
            if chunk == ():
                logging.info("Not recognized as data")
            elif len(chunk) == 2:
                logging.info("Status message: %s" % chunk[1] )
            elif len(chunk) == 6:
                record_position(chunk[0], chunk[2], chunk[3], chunk[4], chunk[5])



class Handler(RequestHandler):

    db = Connection(MONGODB_HOST, MONGODB_PORT)[MONGODB_DB]

    def last(self, imei):
        last_positions = self.db.last_positions
        return last_positions.find_one({"_id": imei})

    def trips(self, obj):
        return obj

if __name__ == '__main__':
    LOG_FILENAME = '/tmp/server.log'
    logging.basicConfig(level=logging.INFO, filename=LOG_FILENAME)

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

    try:
        io_loop.start()
    except KeyboardInterrupt:
        io_loop.stop()
        print "exited cleanly"

