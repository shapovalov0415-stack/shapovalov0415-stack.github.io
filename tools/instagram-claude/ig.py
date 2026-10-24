#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ig.py - Instagram Graph API CLI (Python 3 standard library only).

Reads the access token from the environment, never from an argument:

    export IG_ACCESS_TOKEN=...        # required
    export IG_AUTH_MODE=instagram     # instagram (default) | facebook
    export IG_USER_ID=...             # optional, skips account lookup
    export IG_API_VERSION=v26.0       # optional

Two Meta auth paths are supported because they use different hosts:
  instagram -> https://graph.instagram.com  (Instagram API with Instagram Login)
  facebook  -> https://graph.facebook.com   (Instagram API with Facebook Login)

Every write (reply, hide, delete, publish, dm-send, private-reply) is refused
unless --yes is given; without it the request is printed and nothing is sent.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_VERSION = "v26.0"
HOSTS = {
    "instagram": "https://graph.instagram.com",
    "facebook": "https://graph.facebook.com",
}

ERROR_HINTS = {
    190: "token is invalid or expired - generate a new one and exchange it for a long-lived token",
    102: "session expired - the token was short-lived (1 hour); exchange it for a 60-day token",
    100: "bad parameter or a field the account/media type does not support",
    10: "permission missing - add the scope and, for other people's accounts, pass App Review",
    200: "permission missing for this account (check the account is a professional account)",
    4: "application request limit reached - slow down",
    17: "user request limit reached - slow down",
    9: "publishing limit reached - check `ig.py limit`",
    24: "messaging window closed - you may only reply within 24h of the user's last message",
    36: "comments are disabled on this media",
}


class ApiError(Exception):
    pass


def mask(token):
    if not token:
        return "(none)"
    return token[:6] + "..." + token[-4:] if len(token) > 14 else "***"


def describe_error(payload, http_status):
    err = payload.get("error") or {}
    code = err.get("code")
    parts = [
        "Meta API error",
        "http=%s" % http_status,
        "code=%s" % code,
    ]
    if err.get("error_subcode"):
        parts.append("subcode=%s" % err["error_subcode"])
    msg = err.get("error_user_msg") or err.get("message") or json.dumps(payload)[:400]
    out = " ".join(parts) + ": " + msg
    hint = ERROR_HINTS.get(code)
    if hint:
        out += "\n  hint: " + hint
    return out


class Ctx:
    def __init__(self, args):
        self.token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
        self.mode = (args.mode or os.environ.get("IG_AUTH_MODE") or "instagram").lower()
        if self.mode not in HOSTS:
            raise SystemExit("IG_AUTH_MODE must be 'instagram' or 'facebook', got %r" % self.mode)
        self.host = HOSTS[self.mode]
        self.version = args.api_version or os.environ.get("IG_API_VERSION") or DEFAULT_VERSION
        self.dry_run = args.dry_run
        self.yes = args.yes
        self.raw = args.json
        self._user_id = args.user_id or os.environ.get("IG_USER_ID") or None
        if not self.token and not self.dry_run:
            raise SystemExit(
                "IG_ACCESS_TOKEN is not set.\n"
                "Store it as an environment secret for the session - do not paste it into chat."
            )

    # ---- plumbing -------------------------------------------------------
    def url(self, path, versioned=True, host=None):
        base = host or self.host
        path = str(path).lstrip("/")
        return "%s/%s/%s" % (base, self.version, path) if versioned else "%s/%s" % (base, path)

    def call(self, path, params=None, method="GET", versioned=True, host=None, write=False):
        params = dict(params or {})
        params["access_token"] = self.token
        url = self.url(path, versioned=versioned, host=host)
        shown = dict(params, access_token=mask(self.token))
        if write and not self.yes:
            print("WOULD %s %s" % (method, url))
            print("  params: %s" % json.dumps(shown, ensure_ascii=False))
            print("  refused: pass --yes to actually send this write request.")
            raise SystemExit(2)
        if self.dry_run:
            print("DRY-RUN %s %s" % (method, url))
            print("  params: %s" % json.dumps(shown, ensure_ascii=False))
            return {}
        data = None
        if method == "GET":
            url = url + "?" + urllib.parse.urlencode(params)
        else:
            data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"error": {"message": raw[:400]}}
            raise ApiError(describe_error(payload, exc.code)) from None
        except urllib.error.URLError as exc:
            raise ApiError(
                "network error: %s\n"
                "  hint: a Claude cloud sandbox blocks graph.facebook.com / graph.instagram.com "
                "until the host is added to the environment's allowed domains." % exc.reason
            ) from None
        return json.loads(body) if body.strip() else {}

    def get(self, path, params=None, **kw):
        return self.call(path, params, "GET", **kw)

    def post(self, path, params=None, **kw):
        return self.call(path, params, "POST", write=True, **kw)

    # ---- account --------------------------------------------------------
    def user_id(self):
        if self._user_id:
            return self._user_id
        if self.dry_run:
            return "{ig-user-id}"
        if self.mode == "instagram":
            me = self.get("me", {"fields": "user_id,username"})
            self._user_id = str(me.get("user_id") or me.get("id") or "me")
        else:
            accounts = self.get("me/accounts", {"fields": "name,instagram_business_account{id,username}"})
            for page in accounts.get("data", []):
                iba = page.get("instagram_business_account")
                if iba:
                    self._user_id = str(iba["id"])
                    break
            if not self._user_id:
                raise ApiError(
                    "no Instagram professional account is linked to any Facebook Page on this token.\n"
                    "  hint: link the Instagram account to a Page, or use IG_AUTH_MODE=instagram."
                )
        return self._user_id


def emit(ctx, obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---- commands -----------------------------------------------------------
def cmd_whoami(ctx, args):
    if ctx.mode == "instagram":
        fields = "user_id,username,account_type,media_count,followers_count,follows_count,profile_picture_url"
        emit(ctx, ctx.get("me", {"fields": fields}))
    else:
        pages = ctx.get("me/accounts", {"fields": "id,name,instagram_business_account{id,username,followers_count,media_count}"})
        emit(ctx, pages)


def cmd_media(ctx, args):
    fields = args.fields or "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
    node = "me/media" if ctx.mode == "instagram" else "%s/media" % ctx.user_id()
    emit(ctx, ctx.get(node, {"fields": fields, "limit": args.limit}))


def cmd_top(ctx, args):
    """Rank recent posts by engagement - the '伸びている投稿の分析' use case."""
    node = "me/media" if ctx.mode == "instagram" else "%s/media" % ctx.user_id()
    listing = ctx.get(node, {
        "fields": "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count",
        "limit": args.limit,
    })
    rows = []
    for m in listing.get("data", []):
        row = {
            "id": m.get("id"),
            "type": m.get("media_product_type") or m.get("media_type"),
            "timestamp": m.get("timestamp"),
            "permalink": m.get("permalink"),
            "caption": (m.get("caption") or "")[:60].replace("\n", " "),
            "likes": m.get("like_count"),
            "comments": m.get("comments_count"),
        }
        try:
            ins = ctx.get("%s/insights" % m["id"], {"metric": args.metrics})
            for item in ins.get("data", []):
                vals = item.get("values") or [{}]
                row[item["name"]] = vals[0].get("value")
        except ApiError as exc:
            row["insights_error"] = str(exc).splitlines()[0]
        reach = row.get("reach") or 0
        inter = row.get("total_interactions")
        if inter is None:
            inter = (row.get("likes") or 0) + (row.get("comments") or 0)
            row["total_interactions"] = inter
        row["engagement_rate_pct"] = round(inter / reach * 100, 2) if reach else None
        rows.append(row)
    key = args.sort
    rows.sort(key=lambda r: (r.get(key) is None, -(r.get(key) or 0)))
    emit(ctx, rows)


def cmd_insights(ctx, args):
    node = "me/insights" if ctx.mode == "instagram" else "%s/insights" % ctx.user_id()
    params = {"metric": args.metrics, "period": args.period}
    if args.metric_type:
        params["metric_type"] = args.metric_type
    if args.since:
        params["since"] = args.since
    if args.until:
        params["until"] = args.until
    emit(ctx, ctx.get(node, params))


def cmd_comments(ctx, args):
    fields = "id,text,username,timestamp,like_count,hidden,replies{id,text,username,timestamp}"
    emit(ctx, ctx.get("%s/comments" % args.media_id, {"fields": fields, "limit": args.limit}))


def cmd_reply(ctx, args):
    emit(ctx, ctx.post("%s/replies" % args.comment_id, {"message": args.text}))


def cmd_hide(ctx, args):
    emit(ctx, ctx.post(args.comment_id, {"hide": "false" if args.unhide else "true"}))


def cmd_delete_comment(ctx, args):
    emit(ctx, ctx.call(args.comment_id, {}, "DELETE", write=True))


def cmd_private_reply(ctx, args):
    emit(ctx, ctx.post("%s/messages" % ctx.user_id(), {
        "recipient": json.dumps({"comment_id": args.comment_id}),
        "message": json.dumps({"text": args.text}),
    }))


def cmd_conversations(ctx, args):
    params = {"fields": "id,updated_time,participants", "limit": args.limit}
    if ctx.mode == "facebook":
        params["platform"] = "instagram"
    node = "me/conversations" if ctx.mode == "instagram" else "%s/conversations" % ctx.user_id()
    emit(ctx, ctx.get(node, params))


def cmd_messages(ctx, args):
    emit(ctx, ctx.get(args.conversation_id, {
        "fields": "messages.limit(%d){id,created_time,from,to,message}" % args.limit,
    }))


def cmd_dm_send(ctx, args):
    emit(ctx, ctx.post("%s/messages" % ctx.user_id(), {
        "recipient": json.dumps({"id": args.recipient_id}),
        "message": json.dumps({"text": args.text}),
    }))


def _wait_container(ctx, container_id, timeout_s, interval):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = ctx.get(container_id, {"fields": "status_code,status"})
        code = st.get("status_code")
        if code == "FINISHED":
            return st
        if code in ("ERROR", "EXPIRED"):
            raise ApiError("container %s is %s: %s" % (container_id, code, st.get("status")))
        print("  container %s: %s" % (container_id, code or "?"), file=sys.stderr)
        time.sleep(interval)
    raise ApiError("container %s was not FINISHED within %ss" % (container_id, timeout_s))


def _publish(ctx, container_id, args):
    if args.container_only:
        emit(ctx, {"creation_id": container_id, "published": False})
        return
    if not ctx.dry_run:
        _wait_container(ctx, container_id, args.timeout, args.poll)
    emit(ctx, ctx.post("%s/media_publish" % ctx.user_id(), {"creation_id": container_id}))


def cmd_publish_image(ctx, args):
    params = {"image_url": args.image_url}
    if args.caption:
        params["caption"] = args.caption
    if args.location_id:
        params["location_id"] = args.location_id
    res = ctx.post("%s/media" % ctx.user_id(), params)
    _publish(ctx, res.get("id", "DRY-RUN"), args)


def cmd_publish_reel(ctx, args):
    params = {"media_type": "REELS", "video_url": args.video_url}
    if args.caption:
        params["caption"] = args.caption
    if args.cover_url:
        params["cover_url"] = args.cover_url
    if args.no_share_to_feed:
        params["share_to_feed"] = "false"
    res = ctx.post("%s/media" % ctx.user_id(), params)
    _publish(ctx, res.get("id", "DRY-RUN"), args)


def cmd_publish_story(ctx, args):
    params = {"media_type": "STORIES"}
    if args.image_url:
        params["image_url"] = args.image_url
    elif args.video_url:
        params["video_url"] = args.video_url
    else:
        raise SystemExit("story needs --image-url or --video-url")
    res = ctx.post("%s/media" % ctx.user_id(), params)
    _publish(ctx, res.get("id", "DRY-RUN"), args)


def cmd_publish_carousel(ctx, args):
    children = []
    for url in args.image_url:
        res = ctx.post("%s/media" % ctx.user_id(), {"image_url": url, "is_carousel_item": "true"})
        children.append(res.get("id", "DRY-RUN"))
    if not ctx.dry_run:
        for cid in children:
            _wait_container(ctx, cid, args.timeout, args.poll)
    params = {"media_type": "CAROUSEL", "children": ",".join(children)}
    if args.caption:
        params["caption"] = args.caption
    res = ctx.post("%s/media" % ctx.user_id(), params)
    _publish(ctx, res.get("id", "DRY-RUN"), args)


def cmd_limit(ctx, args):
    emit(ctx, ctx.get("%s/content_publishing_limit" % ctx.user_id(), {"fields": "config,quota_usage"}))


def cmd_token_exchange(ctx, args):
    """Short-lived (1h) -> long-lived (60d). The app secret must stay server-side."""
    secret = os.environ.get("IG_APP_SECRET", "").strip()
    if not secret and not ctx.dry_run:
        raise SystemExit("IG_APP_SECRET is not set (store it as an environment secret, not in chat).")
    if ctx.mode == "instagram":
        res = ctx.call("access_token", {
            "grant_type": "ig_exchange_token",
            "client_secret": secret,
        }, "GET", versioned=False)
    else:
        app_id = os.environ.get("IG_APP_ID", "").strip()
        if not app_id and not ctx.dry_run:
            raise SystemExit("IG_APP_ID is not set.")
        res = ctx.call("oauth/access_token", {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": secret,
            "fb_exchange_token": ctx.token,
        })
    _save_token(res, args.out)


def cmd_token_refresh(ctx, args):
    """Refresh a long-lived Instagram-Login token (>=24h old, not expired)."""
    if ctx.mode != "instagram":
        raise SystemExit("refresh is only for IG_AUTH_MODE=instagram; Facebook-Login tokens are re-exchanged instead.")
    res = ctx.call("refresh_access_token", {"grant_type": "ig_refresh_token"}, "GET", versioned=False)
    _save_token(res, args.out)


def _save_token(res, out):
    token = res.get("access_token")
    if not token:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    with open(out, "w", encoding="utf-8") as fh:
        os.chmod(out, 0o600)
        fh.write(token)
    expires = res.get("expires_in")
    print("wrote %s (mode 600): %s" % (out, mask(token)))
    if expires:
        print("expires_in: %ss (~%.0f days)" % (expires, int(expires) / 86400.0))
    print("Put this value in the environment as IG_ACCESS_TOKEN - do not paste it into a chat.")


def cmd_get(ctx, args):
    params = {}
    for pair in args.param or []:
        if "=" not in pair:
            raise SystemExit("--param expects key=value, got %r" % pair)
        k, v = pair.split("=", 1)
        params[k] = v
    emit(ctx, ctx.get(args.path, params))


# ---- cli ----------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(description="Instagram Graph API CLI (stdlib only)")
    p.add_argument("--mode", choices=sorted(HOSTS), help="auth path (default: $IG_AUTH_MODE or instagram)")
    p.add_argument("--api-version", help="Graph API version (default: $IG_API_VERSION or %s)" % DEFAULT_VERSION)
    p.add_argument("--user-id", help="Instagram professional account id (default: $IG_USER_ID or looked up)")
    p.add_argument("--dry-run", action="store_true", help="print the request instead of sending it")
    p.add_argument("--yes", action="store_true", help="actually perform write operations")
    p.add_argument("--json", action="store_true", help="(reserved) raw json output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="show the account the token belongs to").set_defaults(fn=cmd_whoami)

    m = sub.add_parser("media", help="list recent media")
    m.add_argument("--limit", type=int, default=10)
    m.add_argument("--fields")
    m.set_defaults(fn=cmd_media)

    t = sub.add_parser("top", help="rank recent posts by engagement")
    t.add_argument("--limit", type=int, default=12)
    t.add_argument("--metrics", default="views,reach,total_interactions,saved,shares")
    t.add_argument("--sort", default="engagement_rate_pct")
    t.set_defaults(fn=cmd_top)

    i = sub.add_parser("insights", help="account insights")
    i.add_argument("--metrics", default="views,reach,accounts_engaged,total_interactions")
    i.add_argument("--period", default="day")
    i.add_argument("--metric-type", default="total_value")
    i.add_argument("--since")
    i.add_argument("--until")
    i.set_defaults(fn=cmd_insights)

    c = sub.add_parser("comments", help="list comments on a media")
    c.add_argument("media_id")
    c.add_argument("--limit", type=int, default=25)
    c.set_defaults(fn=cmd_comments)

    r = sub.add_parser("reply", help="[write] reply to a comment")
    r.add_argument("comment_id")
    r.add_argument("text")
    r.set_defaults(fn=cmd_reply)

    h = sub.add_parser("hide", help="[write] hide or unhide a comment")
    h.add_argument("comment_id")
    h.add_argument("--unhide", action="store_true")
    h.set_defaults(fn=cmd_hide)

    d = sub.add_parser("delete-comment", help="[write] delete a comment")
    d.add_argument("comment_id")
    d.set_defaults(fn=cmd_delete_comment)

    pr = sub.add_parser("private-reply", help="[write] DM the author of a comment")
    pr.add_argument("comment_id")
    pr.add_argument("text")
    pr.set_defaults(fn=cmd_private_reply)

    cv = sub.add_parser("conversations", help="list DM threads")
    cv.add_argument("--limit", type=int, default=20)
    cv.set_defaults(fn=cmd_conversations)

    ms = sub.add_parser("messages", help="read one DM thread")
    ms.add_argument("conversation_id")
    ms.add_argument("--limit", type=int, default=20)
    ms.set_defaults(fn=cmd_messages)

    ds = sub.add_parser("dm-send", help="[write] send a DM (24h window applies)")
    ds.add_argument("recipient_id")
    ds.add_argument("text")
    ds.set_defaults(fn=cmd_dm_send)

    def pub_common(sp):
        sp.add_argument("--caption")
        sp.add_argument("--container-only", action="store_true", help="create the container but do not publish")
        sp.add_argument("--timeout", type=int, default=300)
        sp.add_argument("--poll", type=int, default=5)

    pi = sub.add_parser("publish-image", help="[write] publish a single image")
    pi.add_argument("--image-url", required=True, help="public https URL of the image")
    pi.add_argument("--location-id")
    pub_common(pi)
    pi.set_defaults(fn=cmd_publish_image)

    prl = sub.add_parser("publish-reel", help="[write] publish a reel")
    prl.add_argument("--video-url", required=True)
    prl.add_argument("--cover-url")
    prl.add_argument("--no-share-to-feed", action="store_true")
    pub_common(prl)
    prl.set_defaults(fn=cmd_publish_reel)

    pst = sub.add_parser("publish-story", help="[write] publish a story")
    pst.add_argument("--image-url")
    pst.add_argument("--video-url")
    pub_common(pst)
    pst.set_defaults(fn=cmd_publish_story)

    pc = sub.add_parser("publish-carousel", help="[write] publish a carousel of images")
    pc.add_argument("--image-url", action="append", required=True, help="repeat 2-10 times")
    pub_common(pc)
    pc.set_defaults(fn=cmd_publish_carousel)

    sub.add_parser("limit", help="remaining API publishing quota").set_defaults(fn=cmd_limit)

    te = sub.add_parser("token-exchange", help="exchange a short-lived token for a long-lived one")
    te.add_argument("--out", required=True, help="file to write the new token to (mode 600)")
    te.set_defaults(fn=cmd_token_exchange)

    tr = sub.add_parser("token-refresh", help="refresh a long-lived Instagram-Login token")
    tr.add_argument("--out", required=True)
    tr.set_defaults(fn=cmd_token_refresh)

    g = sub.add_parser("get", help="raw GET against any path")
    g.add_argument("path")
    g.add_argument("--param", action="append")
    g.set_defaults(fn=cmd_get)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ctx = Ctx(args)
        args.fn(ctx, args)
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
