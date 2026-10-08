from unittest.mock import patch, Mock

import pytest
import requests
from sqlmodel import select

from test_personal_studio import personal
from reachly.models import Platform, PlatformCredentials, PlatformMode, PostResult
from reachly.platforms.twitter import TwitterApiPoster
from server.crypto import encrypt_dict
from server import x_engagement as x


IDENTITY = {"id": "123456", "username": "shared_account"}


def connect(db, user_id, *, live=True):
    from server.db import User, PlatformCredRow
    with db.get_session() as s:
        user = s.get(User, user_id); user.dry_run = not live
        s.add(user)
        s.add(PlatformCredRow(user_id=user_id, platform="twitter", mode="api", vault=encrypt_dict({
            "oauth2_token": "synthetic", "verified_user_id": IDENTITY["id"], "verified_username": IDENTITY["username"],
            "expected_account": IDENTITY["username"]})))
        s.commit()


def opportunity(db, user_id, *, target="9876"):
    from server.db import User
    with db.get_session() as s:
        user = s.get(User, user_id)
    _, key = x._profile(user)
    row = x.XOpportunity(id=f"{user_id}-{target}", user_id=user_id, business_key=key,
        account_id=IDENTITY['id'], tweet_id=target, author="person", text="A concrete post about agent evaluation.", query="#AI")
    with db.get_session() as s:
        s.add(row); s.commit()
    return f"{user_id}-{target}"


def test_discovery_is_bounded_and_never_sends(personal):
    client, user, _, db, _ = personal
    connect(db, user.id)
    posts = [{"id":"9876", "author":"person", "text":"Use evidence.", "query":"#AI"}]
    with patch.object(TwitterApiPoster, "identity", return_value=IDENTITY), patch.object(TwitterApiPoster, "search_hashtags", return_value=posts) as search, patch.object(TwitterApiPoster, "send_text") as send:
        result=client.post('/x/discover',data={'hashtags':'#AI #MultiAgentAI'})
        assert result.status_code==200 and 'Use evidence.' in result.text
        search.assert_called_once_with(['#AI','#MultiAgentAI'],'shared_account')
        send.assert_not_called()
    with patch.object(TwitterApiPoster, "identity") as identity:
        assert 'one to five' in client.post('/x/discover',data={'hashtags':'from:anyone'}).text
        identity.assert_not_called()


def test_confirmation_dry_run_and_workspace_isolation(personal):
    client, user, _, db, _ = personal
    connect(db,user.id,live=False)
    ident=opportunity(db,user.id)
    with patch.object(TwitterApiPoster,'send_text') as send:
        assert client.post('/x/send',data={'text':'Helpful response'}).status_code==422
        assert 'dry-run' in client.post('/x/send',data={'text':'Helpful response','confirm':'send'}).text
        assert client.post('/x/send',data={'text':'Helpful response','confirm':'send','opportunity_id':'other-workspace'}).status_code==404
        assert client.post('/x/send',data={'text':'Helpful response','confirm':'send'},headers={'Origin':'https://evil.example'}).status_code==403
        send.assert_not_called()


def test_shared_account_blocks_duplicate_posts_between_businesses(personal):
    client,user,_,db,_=personal
    connect(db,user.id)
    result=PostResult(platform=Platform.twitter,ok=True,permalink='https://x.com/i/web/status/555')
    with patch.object(TwitterApiPoster,'identity',return_value=IDENTITY), patch.object(TwitterApiPoster,'send_text',return_value=result) as send:
        assert 'Sent to X' in client.post('/x/send',data={'text':'A useful update','confirm':'send'}).text
        assert client.post('/workspaces',data={'name':'Second business'}).status_code==200
        with db.get_session() as s:
            child=s.exec(select(db.User).where(db.User.owner_user_id==user.id)).one()
        connect(db,child.id)
        assert 'already attempted' in client.post('/x/send',data={'text':'A useful update','confirm':'send'}).text
        send.assert_called_once()


def test_uncertain_reply_is_not_retried(personal):
    client,user,_,db,_=personal
    connect(db,user.id);ident=opportunity(db,user.id)
    with patch.object(TwitterApiPoster,'identity',return_value=IDENTITY), patch.object(TwitterApiPoster,'request_json',return_value={'data':{'id':'9876'}}), patch.object(TwitterApiPoster,'send_text',side_effect=ValueError('Outcome unconfirmed')) as send:
        payload={'text':'Check the evaluation baseline.','confirm':'send','opportunity_id':ident}
        assert 'Outcome unconfirmed' in client.post('/x/send',data=payload).text
        assert 'already attempted' in client.post('/x/send',data=payload).text
        send.assert_called_once()
    with db.get_session() as s:
        assert s.exec(select(x.XAction)).one().state=='check_platform'


def test_changed_x_identity_never_sends(personal):
    client,user,_,db,_=personal
    connect(db,user.id)
    with patch.object(TwitterApiPoster,'identity',return_value={'id':'999','username':'someone_else'}), patch.object(TwitterApiPoster,'send_text') as send:
        assert 'another account' in client.post('/x/send',data={'text':'Hello','confirm':'send'}).text
        send.assert_not_called()


def test_reply_daily_cap_and_stale_business_guard(personal):
    client,user,_,db,_=personal
    connect(db,user.id);ident=opportunity(db,user.id)
    with db.get_session() as s:
        for i in range(5): s.add(x.XAction(id=f'old-{i}',account_id=IDENTITY['id'],user_id=user.id,kind='reply',text='Sent earlier',state='published'))
        s.commit()
    with patch.object(TwitterApiPoster,'identity',return_value=IDENTITY), patch.object(TwitterApiPoster,'request_json',return_value={'data':{'id':'9876'}}), patch.object(TwitterApiPoster,'send_text') as send:
        assert 'daily limit' in client.post('/x/send',data={'text':'Another reply','confirm':'send','opportunity_id':ident}).text
        send.assert_not_called()
    with db.get_session() as s:
        p=s.exec(select(db.BusinessProfileRow).where(db.BusinessProfileRow.user_id==user.id)).one();p.name='Changed identity';s.add(p);s.commit()
    assert client.post(f'/x/{ident}/suggest').status_code==404


def test_ai_suggestion_uses_untrusted_source_and_never_publishes(personal):
    client,user,_,db,_=personal
    connect(db,user.id);ident=opportunity(db,user.id)
    with patch('reachly.llm.LLMClient.generate',return_value='Compare both models against the same task set.') as llm, patch.object(TwitterApiPoster,'send_text') as send:
        page=client.post(f'/x/{ident}/suggest')
        assert 'Compare both models' in page.text
        assert 'untrusted source data' in llm.call_args.args[0]
        send.assert_not_called()


def test_oauth1_get_signature_includes_encoded_search_query():
    p=TwitterApiPoster(PlatformCredentials(platform=Platform.twitter,mode=PlatformMode.api,extra={
        'consumer_key':'key','consumer_secret':'secret','access_token':'token','access_token_secret':'secret2'}))
    with patch('reachly.platforms.twitter.time.time',return_value=123),patch('reachly.platforms.twitter.secrets.token_urlsafe',return_value='nonce'):
        a=p._headers('GET','https://api.x.com/2/tweets/search/recent',{'query':'#AI OR #LLM'})
        b=p._headers('GET','https://api.x.com/2/tweets/search/recent?query=%23AI%20OR%20%23LLM')
        c=p._headers('GET','https://api.x.com/2/tweets/search/recent')
        assert a==b and a!=c


def test_x_error_redacts_provider_body_and_reply_uses_parent_id():
    p=TwitterApiPoster(PlatformCredentials(platform=Platform.twitter,mode=PlatformMode.api,api_token='synthetic'))
    response=Mock(ok=False,status_code=402,text='sensitive provider diagnostics')
    with patch('reachly.platforms.twitter.requests.request',return_value=response):
        with pytest.raises(ValueError,match='Add X API credits') as err:p.identity()
        assert 'sensitive' not in str(err.value)
    with patch.object(p,'request_json',return_value={'data':{'id':'123'}}) as api:
        assert p.send_text('Useful response','987').permalink.endswith('/123')
        assert api.call_args.kwargs['payload']['reply']['in_reply_to_tweet_id']=='987'


def test_invalid_weighted_text_never_calls_x(personal):
    client,user,_,db,_=personal
    connect(db,user.id)
    with patch.object(TwitterApiPoster,'identity') as identity:
        assert 'weighted characters' in client.post('/x/send',data={'text':'界'*200,'confirm':'send'}).text
        identity.assert_not_called()


def test_studio_credential_change_cannot_publish_to_stale_account(personal):
    _, user, _, db, _ = personal
    connect(db, user.id)
    with db.get_session() as s:
        live_user = s.get(db.User, user.id)
    old = PlatformCredentials(platform=Platform.twitter, mode=PlatformMode.api, api_token='old-synthetic')
    publish = Mock()
    with patch.object(TwitterApiPoster, 'identity', return_value=IDENTITY):
        with pytest.raises(ValueError, match='credentials changed'):
            x.guarded_send(live_user, 'Review before sending', publish=publish, expected_credentials=old)
    publish.assert_not_called()
    with db.get_session() as s:
        assert not s.exec(select(x.XAction)).all()
