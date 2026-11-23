from unittest.mock import call, patch

import httpx
import pytest
import respx
from httpx import Response

from app.clients.base import BACKOFF, MAX_ATTEMPTS, RETRYABLE_STATUS_CODES, BaseClient

BASE_URL = "http://testserver"


def _make_client() -> BaseClient:
    return BaseClient(service_url=BASE_URL)


# --- Criterios de aceptación obligatorios ---


@respx.mock
@pytest.mark.parametrize("status_code", (404, 409, 422))
async def test_get_4xx_single_attempt_and_propagates(status_code):
    """4xx en GET: exactamente 1 llamada y se propaga HTTPStatusError."""
    route = respx.get(f"{BASE_URL}/documents/1").mock(
        return_value=Response(status_code, json={"detail": "error"})
    )
    client = _make_client()
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get("/documents/1")
    assert exc_info.value.response.status_code == status_code
    assert route.call_count == 1


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_get_503_then_200_retries_once(mock_sleep):
    """503 en GET seguido de 200: 2 llamadas y éxito."""
    route = respx.get(f"{BASE_URL}/documents/1").mock(
        side_effect=[Response(503), Response(200, json={"id": "1"})]
    )
    client = _make_client()
    resultado = await client.get("/documents/1")
    assert resultado == {"id": "1"}
    assert route.call_count == 2
    mock_sleep.assert_called_once_with(BACKOFF[0])


@respx.mock
async def test_post_503_no_retry():
    """503 en POST: 1 llamada, sin reintento."""
    route = respx.post(f"{BASE_URL}/documents").mock(
        return_value=Response(503, json={"detail": "error"})
    )
    client = _make_client()
    with pytest.raises(httpx.HTTPStatusError):
        await client.post("/documents", json={"foo": "bar"})
    assert route.call_count == 1


# --- Tests adicionales ---


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_post_connect_error_then_success(mock_sleep):
    """POST con ConnectError y luego éxito: reintenta (2 llamadas)."""
    route = respx.post(f"{BASE_URL}/documents").mock(
        side_effect=[
            httpx.ConnectError("connection failed"),
            Response(200, json={"id": "2"}),
        ]
    )
    client = _make_client()
    resultado = await client.post("/documents", json={"foo": "bar"})
    assert resultado == {"id": "2"}
    assert route.call_count == 2
    mock_sleep.assert_called_once_with(BACKOFF[0])


@respx.mock
async def test_post_read_timeout_single_attempt():
    """POST con ReadTimeout: 1 llamada, no se reintenta."""
    route = respx.post(f"{BASE_URL}/documents").mock(
        side_effect=httpx.ReadTimeout("read timeout")
    )
    client = _make_client()
    with pytest.raises(httpx.ReadTimeout):
        await client.post("/documents", json={"foo": "bar"})
    assert route.call_count == 1


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_get_503_permanent_exhausts_attempts(mock_sleep):
    """GET con 503 permanente: se agotan MAX_ATTEMPTS y se lanza HTTPStatusError con esa respuesta."""
    route = respx.get(f"{BASE_URL}/documents/1").mock(
        return_value=Response(503, json={"detail": "unavailable"})
    )
    client = _make_client()
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get("/documents/1")
    assert exc_info.value.response.status_code == 503
    assert route.call_count == MAX_ATTEMPTS
    assert mock_sleep.call_args_list == [call(BACKOFF[0]), call(BACKOFF[1])]


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_delete_502_then_204_retries(mock_sleep):
    """DELETE con 502 y luego 204: reintenta."""
    route = respx.delete(f"{BASE_URL}/documents/1").mock(
        side_effect=[Response(502), Response(204)]
    )
    client = _make_client()
    resultado = await client.delete("/documents/1")
    assert resultado == ""
    assert route.call_count == 2
    mock_sleep.assert_called_once_with(BACKOFF[0])


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_sleeps_match_backoff(mock_sleep):
    """Las esperas usadas coinciden con BACKOFF (0.2, 0.5)."""
    route = respx.get(f"{BASE_URL}/documents/1").mock(
        side_effect=[Response(503), Response(503), Response(200, json={"ok": True})]
    )
    client = _make_client()
    resultado = await client.get("/documents/1")
    assert resultado == {"ok": True}
    assert route.call_count == MAX_ATTEMPTS
    assert mock_sleep.call_args_list == [call(BACKOFF[0]), call(BACKOFF[1])]


@respx.mock
async def test_get_200_json_cuerpo_vacio_devuelve_texto_vacio():
    """200 con Content-Type JSON y cuerpo vacío: no lanza JSONDecodeError, devuelve texto vacío."""
    route = respx.get(f"{BASE_URL}/documents/1").mock(
        return_value=Response(
            200, content=b"", headers={"content-type": "application/json"}
        )
    )
    client = _make_client()
    resultado = await client.get("/documents/1")
    assert resultado == ""
    assert route.call_count == 1


@respx.mock
async def test_delete_204_json_cuerpo_vacio_devuelve_texto_vacio():
    """DELETE 204 con Content-Type JSON y cuerpo vacío: no lanza JSONDecodeError, devuelve texto vacío."""
    route = respx.delete(f"{BASE_URL}/documents/1").mock(
        return_value=Response(
            204, content=b"", headers={"content-type": "application/json"}
        )
    )
    client = _make_client()
    resultado = await client.delete("/documents/1")
    assert resultado == ""
    assert route.call_count == 1


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_delete_502_then_204_json_cuerpo_vacio_reintenta(mock_sleep):
    """DELETE 502 luego 204 con Content-Type JSON y cuerpo vacío: reintenta y devuelve texto vacío."""
    route = respx.delete(f"{BASE_URL}/documents/1").mock(
        side_effect=[
            Response(502),
            Response(204, content=b"", headers={"content-type": "application/json"}),
        ]
    )
    client = _make_client()
    resultado = await client.delete("/documents/1")
    assert resultado == ""
    assert route.call_count == 2
    mock_sleep.assert_called_once_with(BACKOFF[0])


@respx.mock
@patch("app.clients.base.asyncio.sleep")
@pytest.mark.parametrize("status_code", RETRYABLE_STATUS_CODES)
async def test_get_retryable_status_then_success(mock_sleep, status_code):
    """GET con 502/503/504 seguido de 200: reintenta una vez y tiene éxito."""
    route = respx.get(f"{BASE_URL}/documents/1").mock(
        side_effect=[Response(status_code), Response(200, json={"id": "1"})]
    )
    client = _make_client()
    resultado = await client.get("/documents/1")
    assert resultado == {"id": "1"}
    assert route.call_count == 2
    mock_sleep.assert_called_once_with(BACKOFF[0])


@respx.mock
@patch("app.clients.base.asyncio.sleep")
@pytest.mark.parametrize("status_code", (503, 504))
async def test_delete_retryable_status_then_success(mock_sleep, status_code):
    """DELETE con 503/504 seguido de 204: reintenta una vez y tiene éxito."""
    route = respx.delete(f"{BASE_URL}/documents/1").mock(
        side_effect=[Response(status_code), Response(204)]
    )
    client = _make_client()
    resultado = await client.delete("/documents/1")
    assert resultado == ""
    assert route.call_count == 2
    mock_sleep.assert_called_once_with(BACKOFF[0])
