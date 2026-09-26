from atlas.core.masking import MASK, mask_params, mask_secrets_in, mask_text


def test_mask_querystring():
    url = "https://x/searchPostAreaList.do?serviceKey=abc%2Bdef%3D%3D&postOffiId=100&nowPage=1"
    out = mask_text(url)
    assert "abc" not in out and f"serviceKey={MASK}" in out and "postOffiId=100" in out


def test_mask_sgis_params_and_json():
    s = "consumer_key=K1&consumer_secret=S1&accessToken=T1"
    assert mask_text(s) == f"consumer_key={MASK}&consumer_secret={MASK}&accessToken={MASK}"
    body = '{"result":{"accessToken":"tok-123","accessTimeout":"1727000000000"},"errCd":0}'
    assert "tok-123" not in mask_text(body) and "1727000000000" in mask_text(body)


def test_mask_params():
    assert mask_params({"serviceKey": "k", "postOffiId": "100", "ACCESSTOKEN": "t"}) == \
        {"serviceKey": MASK, "postOffiId": "100", "ACCESSTOKEN": MASK}


def test_mask_secrets_in_encoded_forms():
    sec = "a+b/c=="
    s = f"raw {sec} enc a%2Bb%2Fc%3D%3D plus a%2Bb%2Fc%3D%3D"
    out = mask_secrets_in(s, [sec, ""])
    assert sec not in out and "a%2Bb" not in out


def test_mask_kosis_apikey():
    url = "https://kosis.kr/openapi/Param/statisticsParameterData.do?method=getList&apiKey=ZjZjOTI3==&orgId=101"
    out = mask_text(url)
    assert "ZjZjOTI3" not in out and f"apiKey={MASK}" in out and "orgId=101" in out
    assert mask_params({"apiKey": "k", "tblId": "DT_1B04005N"}) == {"apiKey": MASK, "tblId": "DT_1B04005N"}


def test_brief_error_drops_sql_and_bind_values():
    from atlas.core.masking import brief_error

    raw = ("(psycopg.errors.NumericValueOutOfRange) bigint out of range\n[SQL: \n        SELECT h.hist_id\n"
           "  FROM mart.facility_hub h WHERE h.calc_run_id = %(rid)s]\n[parameters: {'rid': '홍길동 010-1234-5678'}]\n"
           "(Background on this error at: https://sqlalche.me/e/20/9h9h)")
    assert brief_error(raw) == "(psycopg.errors.NumericValueOutOfRange) bigint out of range"
    assert brief_error("a\n  b\tc") == "a b c"
    assert len(brief_error("x" * 500)) == 300 and brief_error("x" * 500).endswith("…")
