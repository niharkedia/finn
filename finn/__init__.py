"""FINN: a filtering investor agent for Indian equities."""
import truststore

truststore.inject_into_ssl()  # use the OS trust store, so HTTPS also works behind TLS-inspecting proxies
