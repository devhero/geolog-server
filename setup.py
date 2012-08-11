#!/usr/bin/env python


"""
Copyright 2012 Timur Evdokimov
Licensed under the Apache License, Version 2.0 (the "License"); 
you may not use this file except in compliance with the License. 
You may obtain a copy of the License at 

   http://www.apache.org/licenses/LICENSE-2.0 

Unless required by applicable law or agreed to in writing, software 
distributed under the License is distributed on an "AS IS" BASIS, 
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. 
See the License for the specific language governing permissions and 
limitations under the License. 
"""

from setuptools import setup

try:
    import json
    json = "json"
except ImportError:
    json = "simplejson"

import distutils.core

distutils.core.setup(
    name = "geolog_server",
    version = "0.1",
    packages = ["geolog_server"],
    author = "Timur Evdokimov",
    author_email = "timur@jacum.com",
    url = "https://github.com/jacum/geolog-server",
    license = "http://www.apache.org/licenses/LICENSE-2.0",
    description = "Server-side application based on tornado for geo-logging/tracking application.",

    install_requires = [
        'setuptools',
        'tornado',
        'pymongo',
        'jsonrpclib',
        json
    ],

    packages = [
        'geolog_server',
        'tornadorpc'
    ]
)
