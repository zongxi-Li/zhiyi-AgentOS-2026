import ssl

import httpx

from app.llm import tls_context


def test_verified_context_reuses_trust_only_and_honors_certificate_changes(tmp_path, monkeypatch):
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
        return context
    monkeypatch.setattr(httpx,'create_ssl_context',create)
    monkeypatch.delenv('SSL_CERT_FILE',raising=False)
    monkeypatch.delenv('SSL_CERT_DIR',raising=False)
    tls_context._verified_context.cache_clear()
    try:
        first=tls_context.verified_context()
        assert tls_context.verified_context() is first and len(calls)==1
        certificate=tmp_path/'ca.pem'; certificate.write_text('first fixture')
        monkeypatch.setenv('SSL_CERT_FILE',str(certificate))
        second=tls_context.verified_context()
        assert second is not first and calls[-1]=={'verify':True,'trust_env':True}
        certificate.write_text('updated fixture with different trust')
        assert tls_context.verified_context() is not second
        isolated=tls_context.verified_context(False)
        monkeypatch.setenv('SSL_CERT_FILE',str(tmp_path/'other.pem'))
        assert tls_context.verified_context(False) is isolated
    finally:
        tls_context._verified_context.cache_clear()
