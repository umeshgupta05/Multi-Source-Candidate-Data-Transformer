"""Generate a sample resume PDF for testing.

Run this script to create ``sources/resumes/jane_doe_resume.pdf``.
Requires ``fpdf2``.
"""

from pathlib import Path

from fpdf import FPDF


def generate_sample_resume():
    """Generate a realistic sample resume PDF."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Header: Name ---
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 12, "Jane Doe", new_x="LMARGIN", new_y="NEXT", align="C")

    # --- Contact Info ---
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0, 6,
        "jane.doe@example.com | +1-202-555-0147 | San Francisco, CA",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.cell(
        0, 6,
        "github.com/jdoe-dev | linkedin.com/in/janedoe",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(6)

    # --- Summary ---
    _section_header(pdf, "Summary")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        0, 5,
        "Experienced software engineer with 8+ years building scalable "
        "backend systems and cloud infrastructure. Passionate about "
        "distributed systems, developer experience, and mentoring junior "
        "engineers. Strong communicator with a track record of leading "
        "cross-functional initiatives.",
    )
    pdf.ln(4)

    # --- Experience ---
    _section_header(pdf, "Experience")

    _job_entry(
        pdf,
        company="Acme Corp",
        title="Senior Software Engineer",
        dates="March 2020 - Present",
        bullets=[
            "Led migration of monolithic services to Kubernetes-based microservices",
            "Designed and implemented CI/CD pipelines reducing deploy time by 60%",
            "Mentored team of 4 junior engineers on distributed systems patterns",
        ],
    )

    _job_entry(
        pdf,
        company="PreviousCo",
        title="Software Engineer",
        dates="June 2016 - February 2020",
        bullets=[
            "Built real-time data processing pipeline handling 50K events/sec",
            "Implemented REST APIs serving 10M+ daily requests",
            "Contributed to open-source internal tools adopted across 3 teams",
        ],
    )

    # --- Education ---
    _section_header(pdf, "Education")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "Stanford University", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, "M.S. Computer Science, 2016", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # --- Skills ---
    _section_header(pdf, "Skills")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        0, 5,
        "Python, Go, JavaScript, TypeScript, Kubernetes, Docker, AWS, "
        "Terraform, PostgreSQL, Redis, CI/CD, REST APIs, gRPC, "
        "Distributed Systems, System Design",
    )

    # --- Save ---
    output_dir = Path(__file__).parent.parent / "sources" / "resumes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "jane_doe_resume.pdf"
    pdf.output(str(output_path))
    print(f"Resume generated: {output_path}")


def _section_header(pdf: FPDF, title: str):
    """Draw a section header with a line underneath."""
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)


def _job_entry(pdf: FPDF, company: str, title: str, dates: str, bullets: list[str]):
    """Draw a job entry with company, title, dates, and bullet points."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, f"{company} - {title}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, dates, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for bullet in bullets:
        pdf.cell(8)  # indent
        pdf.cell(0, 5, f"* {bullet}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


if __name__ == "__main__":
    generate_sample_resume()
