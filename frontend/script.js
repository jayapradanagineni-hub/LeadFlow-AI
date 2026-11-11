console.log("LeadFlow JavaScript loaded");
const API = "http://127.0.0.1:8000/api/leads";

const form = document.getElementById("leadForm");
const message = document.getElementById("message");

async function loadLeads() {

    try {

        const response = await fetch(API);
        const leads = await response.json();

        const qualified = leads.filter(
            lead => lead.status === "qualified"
        ).length;

        const rejected = leads.filter(
            lead => lead.status === "rejected"
        ).length;

        document.getElementById("total").textContent = leads.length;
        document.getElementById("qualified").textContent = qualified;
        document.getElementById("rejected").textContent = rejected;

        const table = document.getElementById("leadTable");

        table.innerHTML = "";

        leads.forEach(lead => {

            const row = document.createElement("tr");

            row.innerHTML = `
                <td>${lead.id}</td>
                <td>${lead.name}</td>
                <td>${lead.score ?? "-"}</td>
                <td>${lead.priority ?? "-"}</td>
                <td>${lead.status}</td>
            `;

            table.appendChild(row);

        });

    } catch (error) {

        message.textContent = "Backend connection failed.";

    }

}

form.addEventListener("submit", async function(event) {

    event.preventDefault();

    const lead = {

        name: document.getElementById("name").value,
        email: document.getElementById("email").value,
        phone: document.getElementById("phone").value,
        company: document.getElementById("company").value,
        requirement: document.getElementById("requirement").value,
        budget_inr: Number(document.getElementById("budget").value || 0),
        industry: document.getElementById("industry").value,
        source: document.getElementById("source").value

    };

    try {

        const response = await fetch(API, {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(lead)

        });

        const result = await response.json();

        message.textContent =
            "Result: " + result.status +
            (result.score !== undefined
                ? " | Score: " + result.score + "/100"
                : "");

        await loadLeads();

        if (result.status !== "rejected") {
            form.reset();
        }

    } catch (error) {

        message.textContent = "Unable to connect to backend.";

    }

});

loadLeads();