import base64
import io
import json
import re
import uuid
from unittest.mock import patch
import pytest
from PIL import Image
from test_personal_studio import personal
from reachly import generation_store as store, generation_worker as worker, visual
from reachly.models import GeneratedMedia


def token(client):
    page = client.get('/api-access')
    assert page.status_code == 200
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post('/api-access', data={'csrf': csrf, 'action': 'rotate'})
    assert response.status_code == 200
    return re.search(r'reachly_[A-Za-z0-9_-]{40,}', response.text).group(0)


@pytest.fixture
def api(personal, tmp_path, monkeypatch):
    client, user, web, db, studio = personal
    monkeypatch.setenv('REACHLY_GENERATION_DATA', str(tmp_path/'jobs'))
    access = token(client)
    client.headers.update({'Authorization': 'Bearer ' + access})
    calls = []
    def llm(system, prompt, **kwargs):
        if "themes array" in system:
            return {"themes": ["Bread"]}
        if system == visual.PLAN_SYSTEM:
            return dict(subject='Bread', composition='One loaf', lighting='Natural', palette='Warm', reference_usage='Preserve identity', avoid='Claims')
        return {'theme':'Bread','hook':f'Fresh bread {len(calls)}','body':'Baked daily.','image_prompt':'A loaf','hashtags':['#Bread']}
    def image(prompt, **kwargs):
        calls.append((prompt, kwargs))
        path = kwargs['out_dir']/'fake.png'
        Image.new('RGB', (128,128), 'blue').save(path)
        return GeneratedMedia(kind='image', local_path=str(path))
    with patch.object(worker.LLMClient, 'generate_json', side_effect=llm), patch.object(worker, 'generate_image_gemini', side_effect=image), patch.object(visual, 'review_visual', return_value=visual.Review(relevance=5, brand=5, reference_fidelity=5, visual_integrity=5, claim_safety=5, issues=[])):
        yield client, user, db, access, calls


def send(client, payload=None, key=None):
    return client.post('/api/v1/image-posts', json=payload or {'topic':'Bread','inputs':{'audit':'Local bakery','saas2point0':'Fresh bread'}}, headers={'Idempotency-Key': key or str(uuid.uuid4())})


def test_image_reply_saved_audit_and_idempotency(api):
    client, user, db, access, calls = api
    key = str(uuid.uuid4())
    result = send(client, key=key)
    assert result.status_code == 200, result.text
    data = result.json(); assert data['state'] == 'completed'
    candidate = data['candidates'][0]
    assert candidate['post']['body'] == 'Baked daily.'
    assert Image.open(io.BytesIO(base64.b64decode(candidate['image_base64']))).size == (128,128)
    assert client.get(candidate['image_url']).status_code == 200
    audit = client.get(data['audit_url'])
    assert audit.status_code == 200 and 'final_image_prompt' in audit.text and 'saas2point0' in audit.text
    assert access not in audit.text and 'synthetic' not in audit.text
    assert send(client, key=key).json()['job_id'] == data['job_id'] and len(calls) == 1
    assert send(client, {'topic':'Other'}, key).status_code == 409
    assert client.get(data['status_url'], headers={'Authorization':'Bearer invalid'}).status_code == 401


def test_token_rotation_csrf_revocation_and_workspace_isolation(api):
    client, user, db, access, calls = api
    job = send(client).json()
    assert client.post('/api-access', data={'csrf':'wrong','action':'rotate'}).status_code == 403
    replacement = token(client)
    assert client.get(job['status_url'], headers={'Authorization':'Bearer '+access}).status_code == 401
    client.headers['Authorization'] = 'Bearer ' + replacement
    assert client.get(job['status_url']).status_code == 200
    with db.get_session() as session:
        other = db.User(owner_user_id=user.id, is_active=True); session.add(other); session.commit(); session.refresh(other)
        from server.image_post_api import ImageApiKey
        from server.studio import _key
        import hashlib
        profile = db.BusinessProfileRow(user_id=other.id,name='Other')
        session.add(profile); session.add(ImageApiKey(user_id=other.id,digest=hashlib.sha256(b'other-token').hexdigest(),business_key=_key(profile)));session.commit()
    assert client.get(job['status_url'], headers={'Authorization':'Bearer other-token'}).status_code == 404
    assert client.get(job['audit_url'], headers={'Authorization':'Bearer other-token'}).status_code == 404
    assert client.get(job['candidates'][0]['image_url'], headers={'Authorization':'Bearer other-token'}).status_code == 404
    page = client.get('/api-access'); csrf=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
    client.post('/api-access',data={'csrf':csrf,'action':'revoke'})
    assert client.get(job['status_url']).status_code == 401


def test_revision_keeps_copy_and_sends_original_pixels_and_feedback(api):
    client, user, db, access, calls = api
    first = send(client).json(); item = first['candidates'][0]
    second = send(client, {'topic':'Bread', 'original':{'job_id':first['job_id'],'candidate_id':item['id']},
                           'revision_mode':'image','feedback':'Use a green background'}).json()
    assert second['state'] == 'completed', second
    assert second['candidates'][0]['post']['body'] == item['post']['body']
    assert calls[1][1]['reference_images'][0]['role'] == 'original'
    assert 'Use a green background' in calls[1][0]
    assert calls[1][1]['reference_images'][0]['data']


def test_failed_review_holds_asset_and_records_reason(api):
    client, user, db, access, calls = api
    with patch.object(visual, 'review_visual', return_value=visual.Review(relevance=1, brand=5, reference_fidelity=5, visual_integrity=5, claim_safety=5, issues=['Wrong subject'])):
        data = send(client).json()
    assert data['state'] == 'failed'
    item = data['candidates'][0]
    assert 'image_base64' not in item
    assert client.get(data['status_url']+'/image/'+item['id']).status_code == 404
    assert 'Wrong subject' in client.get(data['audit_url']).text
    assert len(calls) == 1


def test_validation_before_any_paid_call_and_no_cookie_auth(api):
    client, user, db, access, calls = api
    assert send(client, {'business':{'name':'Another company'}}).status_code == 422
    assert send(client, {'references':[{'role':'product','image_base64':'garbage'}]}).status_code == 422
    assert send(client, {'visual':{'aspect_ratio':'9:99'}}).status_code == 422
    assert send(client, {'topic':'a'}, 'not-uuid').status_code == 422
    client.headers.pop('Authorization')
    assert send(client).status_code == 401
    assert not calls


def test_rate_limit_and_specific_atomic_claim(api):
    client, user, db, access, calls = api
    for i in range(10): assert send(client).status_code == 200
    assert send(client).status_code == 429
    assert len(calls) == 10
    assert store.claim() is None


def test_completed_job_is_not_reexecuted_by_competing_workers(api):
    from concurrent.futures import ThreadPoolExecutor
    from server.image_post_api import execute
    client, user, db, access, calls = api
    data = send(client).json()
    row = store.get(data['job_id'], f'personal-{user.id}')
    with patch('server.image_post_api.process') as process:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: execute(row, {}), range(2)))
    process.assert_not_called()


def test_two_claimants_execute_one_queued_job(api):
    from concurrent.futures import ThreadPoolExecutor
    from server.image_post_api import execute
    client, user, db, access, calls = api
    row = store.submit(f'personal-{user.id}', str(uuid.uuid4()), {'business_id':'test'}, 'personal-workspace')
    with patch('server.image_post_api.process') as process:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: execute(row, {}), range(2)))
    assert process.call_count == 1
    assert store.get(row['id'], row['owner'])['state'] == 'running'
