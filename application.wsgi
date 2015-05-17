#!/usr/bin/env python3
# vim:fileencoding=utf-8:ts=8:et:sw=4:sts=4:tw=79

"""
application.wsgi

The "ScrobbLRR" bottle application.

Copyright (c) 2015 Twisted Pear <pear at twistedpear dot at>
See the file LICENSE for copying permission.
"""

from bottle import Bottle, request, response
from bottle.ext import redis
from hashlib import md5
from os import environ
from uuid import uuid4

app = application = Bottle()
redis_plugin = redis.RedisPlugin()
app.install(redis_plugin)

EXPIRATION_SEC = int(environ.get("EXPIRATION_SEC", 300))
NOWPLAYING_URL = environ["NOWPLAYING_URL"]
SUBMISSION_URL = environ["SUBMISSION_URL"]


@app.get("/")
def handshake(rdb):
    """
    The initial negotiation with the Audioscrobbler server to establish
    authentication and connection details for the session.
    """
    # all we return here is plain text
    response.content_type = "text/plain"

    # is this really a handshake?
    if request.query.get("hs") != "true":
        return "ScrobbLRR submissions system."

    # we only support protocol version 1.2(.1)
    proto = request.query.get("p")
    if proto != "1.2" and proto != "1.2.1":
        return "FAILED Incorrect protocol version"

    # now we need to try and authenticate the user
    user = request.query.get("u")
    time = request.query.get("t")
    auth = request.query.get("a")
    if not all((user, time, auth)):
        return "BADAUTH Incomplete credentials"

    # get credentials for that user (if any)
    ckey = "scrobblrr:user:{user}:cred".format(user=user)
    cred = rdb.get(ckey)
    if not cred:
        return "BADAUTH Invalid user name"

    # calculate token := md5(md5(password) + timestamp)
    ch = md5()
    ch.update(cred)

    th = md5()
    th.update(ch.hexdigest().encode())
    th.update(time.encode())

    token = th.hexdigest()
    if auth != token:
        return "BADAUTH Invalid credentials"

    with rdb.pipeline() as pipe:
        # in case we already have a session, get rid of that now
        skey = "scrobblrr:user:{user}:session".format(user=user)
        session = rdb.get(skey)
        if session:
            pipe.delete(skey)
            pipe.hdel("scrobblrr:sessions", session)
            pipe.execute()

        # now we can store a new session
        session = uuid4().hex
        pipe.set(skey, session)
        pipe.hset("scrobblrr:sessions", session, user)
        pipe.execute()

    return ("OK\n"
            "{session}\n"
            "{nowplaying}\n"
            "{submission}".format(
                session=session,
                nowplaying=NOWPLAYING_URL, submission=SUBMISSION_URL))


@app.post("/nowplaying")
def nowplaying(rdb):
    """
    Optional lightweight notification of now-playing data at the start of the
    track for realtime information purposes.
    """
    # all we return here is plain text
    response.content_type = "text/plain"

    # first of all, check the session and get the user
    session = request.forms.get("s")
    user = rdb.hget("scrobblrr:sessions", session)
    if not user:
        return "BADSESSION"

    # make sure we handle the name as string
    user = user.decode("ascii")

    # we only care for artist and track
    artist = request.forms.get("a")
    track = request.forms.get("t")

    if all((artist, track)):
        npkey = "scrobblrr:user:{user}:nowplaying".format(user=user)
        with rdb.pipeline() as pipe:
            pipe.hmset(npkey, {"artist": artist, "track": track})
            pipe.expire(npkey, EXPIRATION_SEC)
            pipe.execute()

    # everything worked out
    return "OK"


@app.post("/submission")
def submission(rdb):
    """
    Submission of full track data at the end of the track for statistical
    purposes.
    """
    # all we return here is plain text
    response.content_type = "text/plain"

    # first of all, check the session and get the user
    session = request.forms.get("s")
    user = rdb.hget("scrobblrr:sessions", session)
    if not user:
        return "BADSESSION"

    # make sure we handle the name as string
    user = user.decode("ascii")

    # we only care for artist and track
    artist = request.forms.get("a[0]")
    track = request.forms.get("t[0]")

    if all((artist, track)):
        npkey = "scrobblrr:user:{user}:submission".format(user=user)
        with rdb.pipeline() as pipe:
            pipe.hmset(npkey, {"artist": artist, "track": track})
            pipe.expire(npkey, EXPIRATION_SEC)
            pipe.execute()

    # everything worked out
    return "OK"


if __name__ == "__main__":
    # we start a local dev server when this file is executed as a script
    from bottle import run
    run(app=application,
        host="dev.pump19.eu", port=8081,
        reloader=True, debug=True)
