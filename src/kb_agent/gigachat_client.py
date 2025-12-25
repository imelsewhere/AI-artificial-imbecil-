from __future__ import annotations

from dataclasses import dataclass

from langchain_gigachat.chat_models import GigaChat as LangchainGigaChat

from kb_agent.config import GigaChatSettings


@dataclass(frozen=True)
class GigaChatRuntime:
    """
    Простой контейнер: настройки + готовый LangChain LLM.
    """

    settings: GigaChatSettings
    llm: LangchainGigaChat


class GigaChat:
    """
    Обёртка над `langchain-gigachat`, как вы просили: здесь задаются base_url/token/model и т.д.

    Поддерживает два режима:
    - **access_token** уже есть → используем его (параметр access_token)
    - **authorization_key** есть → используем его как credentials (библиотека сама получает access_token)
    """

    def __init__(self, settings: GigaChatSettings):
        self.settings = settings
        self._llm = None

    def build(self) -> GigaChatRuntime:
        if not self.settings.access_token and not self.settings.authorization_key:
            raise ValueError("Need either GIGACHAT_ACCESS_TOKEN or GIGACHAT_AUTHORIZATION_KEY in env/.env")

        # Убираем возможный префикс "Basic " (в .env надо хранить только base64-строку).
        credentials = (self.settings.authorization_key or "").strip()
        if credentials.lower().startswith("basic "):
            credentials = credentials.split(" ", 1)[1].strip()

        if not self.settings.verify_ssl_certs:
            # Убираем шумный warning при verify_ssl_certs=false
            try:  # pragma: no cover
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass

        kwargs = dict(
            base_url=self.settings.base_url,
            model=self.settings.model,
            verify_ssl_certs=bool(self.settings.verify_ssl_certs),
            scope=self.settings.scope,
            timeout=float(self.settings.timeout_s),
        )

        # В `langchain-gigachat`:
        # - credentials = Authorization Data (base64)
        # - access_token = temporary token
        if self.settings.access_token:
            llm = LangchainGigaChat(access_token=self.settings.access_token, **kwargs)
        else:
            llm = LangchainGigaChat(credentials=credentials, **kwargs)

        self._llm = llm
        return GigaChatRuntime(settings=self.settings, llm=llm)


