#!/usr/bin/env python
from __future__ import division
from systemd import journal
import re
import sys
import pymongo
from pymongo import MongoClient
import json
import os
import subprocess
import requests
import time
from requests_futures.sessions import FuturesSession

db_info = sys.argv[1]
loginData = "DATABASE_CONNECTION"
db = MongoClient(loginData)
client = db.BotData
collection = client.ValAddrID

KEY="TELEGRAM_KEY"
TIME="10"
URL="https://api.telegram.org/bot" + KEY + "/sendMessage"

j = journal.Reader()
j.this_boot()
j.seek_tail()
# Important! - Discard old journal entries
j.get_previous()
j.log_level(journal.LOG_INFO)
j.add_match(_SYSTEMD_UNIT="forboled.service")

chatidset = set()
start = time.time()

# if no keep track table, add a row to keep track which record has been sent
if (not "keeper" in db["BotData"].collection_names()):
    mykeeper = client["keeper"]
    newrecord = {"_id": 1, "last": 2}
    mykeeper.insert_one(newrecord)
    startrow = 2

# if no records table, create a new one
if (not "Records" in db["BotData"].collection_names()):
    myrecords = client["Records"]
    firstrecord = {"_id": 1, "content": "welcome"}
    myrecords.insert_one(firstrecord)

    # if keeper exist, update last col
    if ("keeper" in db["BotData"].collection_names()):
        newvalue = {"$set": {"last": 2}}
        client.keeper.update({"_id": 1}, newvalue, upsert = False)
    startrow = 2

# use time stamp to keep counting the running time

try:
  while True:
        instart = time.time()
        for entry in j:
            # match Absent validator
            matchAbsent = re.search(r'/.*I\[([0-9]{2}-[0-9]{2})\|([0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3})\] Absent validator ([0-9A-F]{40}) at height ([0-9]{1,}), ([0-9]{1,}) signed, threshold ([0-9]{1,}).*/' , str(entry))
            # match how many shares and tokens reduced
            matchReduced = re.search(r'/.*I\[([0-9]{2}-[0-9]{2})\|([0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3})\] Validator ([0-9A-F]{40}) slashed by slashFactor ([0-9]{1,}\/[0-9]{1,}), burned ([0-9]{1,}\/[0-9]{1,}) tokens.*/', str(entry))
            # match revoke
            matchRevoke = re.search(r'/.*I\[([0-9]{2}-[0-9]{2})\|([0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3})\] Validator ([0-9A-F]{40}) revoked.*/', str(entry))

            # get the message that will be send out
            msg = entry["MESSAGE"]

            if (matchAbsent):
                # get valaddr
                date = matchAbsent.group(1)
                ttime = matchAbsent.group(2)
                valaddr = matchAbsent.group(3)
                height = matchAbsent.group(4)
                signed = matchAbsent.group(5)
                id = client.Records.count() + 1
                doubles = int(matchAbsent.group(6))*2
                uptime = int(signed)/(float(doubles))

                # build json msg
                storejson = '{"validator\": "' + valaddr + '", "absent height\": "' + height + '", "uptime\": "' + str(uptime) + ' (' + signed + '/' + str(doubles) + 'signed)", \"slashing threshold\": "' + matchAbsent.group(6) + '/' + str(doubles) + '\"}'

                # build send msg
                sendmsg = "Type: Absent\\nValidator: " + valaddr + "\\nHeight: " + height + "\\nUptime: " + str(uptime) + " (" + signed + "/" + str(doubles) + " signed)" + "\\nThreshold: " + matchAbsent.group(6) + "/" + str(doubles) + "\\nDate(mm-dd): " + date + "\\nTime: " + ttime

                # store valaddr and content into db
                stringjson = '{"_id": ' + str(id) + ', "ValAddr\": "' + valaddr + '", "content": "' + msg + '", \"msgjson": ' + storejson + ', "type\": "' + 'absent' + '", "sendmsg": "' + sendmsg + '"}'

            elif (matchReduced):
                date = matchAbsent.group(1)
                ttime = matchAbsent.group(2)
                id = client.Records.count() + 1
                valaddr = matchReduced.group(3)
                fraction = matchReduced.group(4)
                burned = matchReduced.group(5)

                storejson = '{"validator\": "' + valaddr + '", "fraction": "' + fraction + '", "burned": "' + burned + '"}'
                sendmsg = "Type: Slashed\\nValidator: " + valaddr + "\\nSlash factor: " + fraction + "\\nBurned token: " + burned + "\\nDate(mm-dd): " + date + "\\nTime: " + ttime
                stringjson = '{"_id": ' + str(id) + ', "ValAddr\": "' + valaddr + '\", "content": "' + msg + '\", "type": "slashed", \"msgjson": ' + storejson + ', "sendmsg\": "' + sendmsg + '"}'

            elif (matchRevoke):
                id = client.Records.count() + 1
                date = matchAbsent.group(1)
                ttime = matchAbsent.group(2)
                valaddr = matchRevoke.group(3)
                storejson = '{"validator\": "' + valaddr + '"}'
                sendmsg = "Type: Revoke\\nValidator: " + valaddr + "\\nDate(mm-dd): " + date + "\\nTime: " + ttime
                stringjson = '{"_id": ' + str(id) + ', "ValAddr\": "' + valaddr + '\", "content": "' + msg + '\", "type": "revoked", \"msgjson": '+ storejson + ', "sendmsg\": "' + sendmsg + '"}'

            # store that record into db Records
            if (matchAbsent or matchReduced or matchRevoke):
                data = json.loads(stringjson)
                client.Records.insert_one(data)
            inend = time.time()
            if (inend - instart > 30):
                break

        end = time.time()
        # send msg every 15 seconds (from keeper.last to current record_id)
        if (end - start > 15):
            instart2 = time.time()
            # get the last height in collection keeper
            startrow = client.keeper.find_one({"_id": 1}).get("last")
            print("startrow: " + str(startrow) + '\n')

            # get the valAddr from that record
            # get the message that will be send out (use for loop)
            # loop from last height to latest record
            for row in range(startrow, client.Records.count()+1):
                # get the content of that record id
                queryjson = '{"_id": ' + str(row) + '}'
                query = json.loads(queryjson)
                try:
                    data = client.Records.find_one(query)
                    sendmsg = data.get("sendmsg")
                    valAddr = data.get("ValAddr")
                    msgtype = data.get("type")
                    print("msgtype: "+msgtype)
                except:
                    break

                # check if the validator is exist in the db.
                # query the chat ID by validator
                stringjson = '{"ValAddr": \"' + valAddr + '\"}'
                for record in collection.find(json.loads(stringjson)):
                    chatid = str(record.get("chatID"))
                    mute = record.get(msgtype)
                    print(mute)
                    if (mute == False):
                        chatidset.add(chatid)
                chatids = tuple(chatidset)
                print(chatids)

                # if there are chatids, send message by API
                session = FuturesSession()
                for id in chatids:
                    session.get("https://api.telegram.org/bot"+KEY+"/sendMessage?chat_id=" + id + "&text=" + sendmsg)
                chatidset = set()

                newvalue = '{"$set": {"last": ' + str(row+1) + '}}'
                try:
                    client.keeper.update({"_id": 1}, json.loads(newvalue), upsert = False)
                except:
                    print("bad update")
                    break
                inend2 = time.time()
                if(inend2 - instart2 > 60):
                    break

#            startrow = client.Records.count()+1
#            newvalue = '{"$set": {"last": ' + str(startrow) + '}}'
#            try:
#                client.keeper.update({"_id": 1}, json.loads(newvalue), upsert = False)
#            except:
#                print("bad update")
#                break
            start = time.time()
            instart = time.time()


except KeyboardInterrupt:
    db.close()
    print("database closed")

