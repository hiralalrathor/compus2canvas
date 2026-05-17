const root = document.querySelector("[data-chatbot]");

if (root) {
    const launch = root.querySelector(".chatbot-launch");
    const panel = root.querySelector(".chatbot-panel");
    const close = root.querySelector(".chatbot-head button");
    const messages = root.querySelector(".chatbot-messages");

    const addMessage = (text, type = "bot", link = "") => {
        const bubble = document.createElement("p");
        bubble.className = type;
        bubble.textContent = text;
        messages.appendChild(bubble);
        if (link) {
            const anchor = document.createElement("a");
            anchor.className = "button small";
            anchor.href = link;
            anchor.textContent = "Open";
            messages.appendChild(anchor);
        }
        messages.scrollTop = messages.scrollHeight;
    };

    launch.addEventListener("click", () => {
        panel.hidden = !panel.hidden;
    });

    close.addEventListener("click", () => {
        panel.hidden = true;
    });

    root.querySelectorAll("[data-intent]").forEach((button) => {
        button.addEventListener("click", async () => {
            const intent = button.dataset.intent;
            addMessage(button.textContent, "user");
            try {
                const response = await fetch(`/chatbot?intent=${encodeURIComponent(intent)}`);
                const data = await response.json();
                addMessage(data.reply, "bot", data.link);
            } catch (error) {
                addMessage("Sorry, I could not answer right now. Please try again.");
            }
        });
    });
}
