"""
app.py
UI Streamlit untuk chatbot Yele — Asisten Perencanaan Bisnis AI.
Jalankan dengan: streamlit run app.py
"""

import asyncio
import sys

# Redam noise ConnectionResetError dari asyncio ProactorEventLoop di Windows.
# Ini quirk umum Windows saat koneksi HTTP async ditutup mendadak oleh
# server (biasanya dari library seperti ddgs/httpx) — tidak menghentikan
# aplikasi, hanya bikin terminal berisik.
if sys.platform.startswith("win"):
    def _silence_proactor_exception(loop, context):
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError):
            return
        loop.default_exception_handler(context)

    class _QuietProactorPolicy(asyncio.WindowsProactorEventLoopPolicy):
        def new_event_loop(self):
            loop = super().new_event_loop()
            loop.set_exception_handler(_silence_proactor_exception)
            return loop

    asyncio.set_event_loop_policy(_QuietProactorPolicy())

import os
import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, AIMessage

from chains import build_agent_executor

load_dotenv()

FALLBACK_MODELS = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
]

# Allowlist model chat yang terkonfirmasi mendukung tool calling di Groq.
# Model lain (Whisper/audio, Llama Guard/safety, TTS, dll) sengaja TIDAK
# dimasukkan karena tidak mendukung tool calling sama sekali, meskipun
# muncul di endpoint /models. groq/compound juga dikecualikan karena
# punya tools bawaan sendiri yang bisa bentrok dengan tools custom kita.
TOOL_CAPABLE_ALLOWLIST = {
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
    "moonshotai/kimi-k2-instruct-0905",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
}


@st.cache_data(ttl=300, show_spinner=False)
def get_available_models(api_key: str) -> list[str]:
    """
    Ambil daftar model yang benar-benar bisa diakses oleh API key ini
    DAN mendukung tool calling, dengan cara mengiriskan hasil dari Groq
    API /models dengan TOOL_CAPABLE_ALLOWLIST.
    """
    try:
        client = Groq(api_key=api_key)
        models = client.models.list()
        available_ids = {m.id for m in models.data}
        usable = sorted(available_ids & TOOL_CAPABLE_ALLOWLIST)
        return usable or FALLBACK_MODELS
    except Exception:
        return FALLBACK_MODELS

QUICK_ACTIONS = {
    "🌱 Saya Baru Mau Mulai (Belum Tahu Apa-apa)": (
        "Aku mau mulai bisnis tapi masih bingung dan belum tahu "
        "angka-angka penting apa saja yang aku butuhkan. Tolong bantu "
        "aku dari awal."
    ),
    "🧮 Hitung Biaya Produksi": (
        "Tolong bantu aku hitung biaya produksi. Aku akan kasih tahu "
        "biaya bahan baku, tenaga kerja, overhead, dan jumlah unitnya."
    ),
    "💰 Hitung Harga Jual": (
        "Tolong bantu aku hitung rekomendasi harga jual dari biaya "
        "produksi per unit dan target margin yang aku mau."
    ),
    "📊 Hitung Margin": (
        "Tolong bantu aku hitung margin keuntungan dari harga jual dan "
        "biaya produksi yang sudah aku punya."
    ),
    "📈 Hitung BEP (Titik Impas)": (
        "Tolong bantu aku hitung BEP (Break Even Point) usahaku."
    ),
}


def init_session_state():
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Halo! Aku **Yele** 👋, siap bantu kamu merencanakan, "
                    "mendirikan, atau menjalankan bisnismu — termasuk "
                    "hitung-hitungan biaya produksi, harga jual, margin, "
                    "sampai BEP. Mau mulai dari mana?"
                ),
            }
        ]
    if "lc_history" not in st.session_state:
        st.session_state.lc_history = []
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None


def render_sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.title("⚙️ Pengaturan Yele")

        env_key = os.getenv("GROQ_API_KEY", "")
        groq_api_key = st.text_input(
            "🔑 Groq API Key",
            value=env_key,
            type="password",
            help="Bisa juga di-set lewat file .env sebagai GROQ_API_KEY",
        )

        model_options = get_available_models(groq_api_key) if groq_api_key else FALLBACK_MODELS
        model_name = st.selectbox(
            "🧠 Pilih Model",
            model_options,
            index=0,
            help=(
                "Daftar ini diambil langsung dari akun Groq kamu (kalau API key "
                "sudah diisi), jadi hanya menampilkan model yang benar-benar bisa "
                "kamu akses. Model non-reasoning seperti llama-3.1-8b-instant "
                "umumnya paling stabil untuk tool calling custom."
            ),
        )

        st.markdown("---")
        st.subheader("Quick Actions")
        for label, template_prompt in QUICK_ACTIONS.items():
            if st.button(label, use_container_width=True):
                st.session_state.pending_prompt = template_prompt

        st.markdown("---")
        if st.button("🔄 Reset Percakapan", use_container_width=True):
            st.session_state.messages = []
            st.session_state.lc_history = []
            init_session_state()
            st.rerun()

        st.markdown("---")
        st.caption(
            "Yele tidak menyimpan API key kamu di server manapun. "
            "Key hanya dipakai selama sesi browser ini berjalan."
        )

    return groq_api_key, model_name


def render_chat_history():
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


class ChatProgressCallback(BaseCallbackHandler):
    """Show high-level agent progress without exposing private reasoning."""

    def __init__(self, status):
        self.status = status

    def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized.get("name", "tool")
        self.status.write(f"🔎 Menggunakan `{tool_name}`...")
        if input_str:
            self.status.write(f"Input: `{input_str}`")

    def on_tool_end(self, output, **kwargs):
        self.status.write("✅ Tool selesai.")

    def on_tool_error(self, error, **kwargs):
        self.status.write(f"⚠️ Tool mengalami masalah: {error}")

    def on_llm_start(self, serialized, prompts, **kwargs):
        self.status.write("💬 Menyusun jawaban...")


def handle_user_input(user_input: str, groq_api_key: str, model_name: str):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.status("Yele sedang menganalisis...", expanded=True) as progress:
            progress_callback = ChatProgressCallback(progress)
            try:
                agent_executor = build_agent_executor(groq_api_key, model_name)
                result = agent_executor.invoke(
                    {
                        "input": user_input,
                        "chat_history": st.session_state.lc_history,
                    },
                    config={"callbacks": [progress_callback]},
                )
                response_text = result["output"]
                progress.update(label="Yele selesai menjawab", state="complete")
            except Exception as e:
                progress.update(label="Yele mengalami kendala", state="error")
                error_str = str(e)
                if "Failed to parse tool call arguments as JSON" in error_str:
                    response_text = (
                        "⚠️ Yele sempat salah format saat menghitung (bukan salah "
                        "kamu). Coba ulangi lagi pesannya, atau tulis angkanya "
                        "polos tanpa singkatan, misal `2000000` daripada `2jt` "
                        "atau `2.000.000`."
                    )
                else:
                    response_text = (
                        "⚠️ Waduh, ada masalah saat menghubungi Yele. "
                        f"Detail error: `{e}`\n\n"
                        "Coba cek kembali Groq API Key atau pilihan model kamu."
                    )

        st.markdown(response_text)

    st.session_state.messages.append({"role": "assistant", "content": response_text})
    st.session_state.lc_history.append(HumanMessage(content=user_input))
    st.session_state.lc_history.append(AIMessage(content=response_text))


def main():
    st.set_page_config(page_title="Yele — Business Planning Assistant", page_icon="🧑‍💼")
    st.title("🧑‍💼 Yele — Asisten Perencanaan Bisnis")
    st.caption("Ditenagai oleh Groq + LangChain")

    init_session_state()
    groq_api_key, model_name = render_sidebar()

    render_chat_history()

    # Ambil prompt dari quick action (jika ada) atau dari chat input biasa
    user_input = st.chat_input("Ketik pesan untuk Yele...")
    if st.session_state.pending_prompt:
        user_input = st.session_state.pending_prompt
        st.session_state.pending_prompt = None

    if user_input:
        if not groq_api_key:
            st.error(
                "Masukkan Groq API Key terlebih dahulu di sidebar sebelum "
                "mulai chat dengan Yele."
            )
        else:
            handle_user_input(user_input, groq_api_key, model_name)


if __name__ == "__main__":
    main()
