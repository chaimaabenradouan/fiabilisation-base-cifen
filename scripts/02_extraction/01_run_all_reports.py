#!/usr/bin/env python3
"""
run_all_reports.py - Lanceur batch robuste pour mineru_extract_tables.py

Fonctionnalités principales :
- Reprise automatique après interruption (coupure, crash, Ctrl+C, ...)
- Détection robuste des PDF déjà traités (dossier selected_tables/*.png + registre completed.json)
- États explicites par PDF : SUCCESS / SKIPPED / FAILED
- Rapport final précis + batch_report.json détaillé
- Option --retry-failed pour ne relancer que les échecs précédents
- Option --max-pdf-size-mb pour ignorer les PDF trop volumineux (RAM/CPU
  limités, pas de GPU dédié) ; ils sont listés dans large_pdfs.json
- Option --max-pages (défaut : 20) : les PDF de plus de N pages sont
  considérés volumineux et ignorés (SKIPPED_LARGE)
- Barres de progression globale + par entreprise, temps moyen, ETA
- Logs propres (console + errors.log)

NOTE IMPORTANTE : mineru_extract_tables.py n'est jamais modifié.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from tqdm import tqdm

try:
    from pypdf import PdfReader
except ImportError:  # fallback éventuel
    PdfReader = None  # type: ignore

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #

DEFAULT_RAPPORTS_DIR = Path("Rapports")
DEFAULT_OUTPUT_DIR = Path("output")

ERROR_LOG_NAME = "errors.log"
COMPLETED_REGISTRY_NAME = "completed.json"
FAILED_REGISTRY_NAME = "failed_pdfs.json"
LARGE_REGISTRY_NAME = "large_pdfs.json"
BATCH_REPORT_NAME = "batch_report.json"

SELECTED_TABLES_DIRNAME = "selected_tables"

# Limite de pages par défaut : au-delà, le PDF est considéré volumineux
# (SKIPPED_LARGE) et listé dans large_pdfs.json pour un traitement ultérieur.
DEFAULT_MAX_PAGES = 20

# Chemin réel du script appelé pour chaque PDF.
# Résolu relativement à l'emplacement de CE fichier (run_all_reports.py),
# et non au dossier courant : le batch fonctionne donc peu importe d'où
# on lance la commande "python run_all_reports.py".
MINERU_SCRIPT_PATH = str(Path(__file__).resolve().parent / "mineru_extract_tables.py")

log = logging.getLogger("batch_runner")


# --------------------------------------------------------------------------- #
# États de traitement
# --------------------------------------------------------------------------- #

class RunStatus(str, Enum):
    """État final du traitement d'un PDF."""
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    SKIPPED_LARGE = "SKIPPED_LARGE"  # PDF trop volumineux, non traité (à refaire plus tard)


@dataclass
class PdfJob:
    """Représente un PDF à traiter et son dossier de sortie."""
    company: str
    year: str
    pdf_path: Path
    output_dir: Path

    @property
    def key(self) -> str:
        """Clé unique utilisée dans le registre completed.json."""
        return f"{self.company}/{self.year}"


@dataclass
class BatchStats:
    """Compteurs et détails accumulés pendant le batch."""
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    skipped_large: int = 0
    errors: list[dict] = field(default_factory=list)
    large_pdfs: list[dict] = field(default_factory=list)

    def record(self, job: PdfJob, status: RunStatus, error_message: Optional[str] = None,
               size_mb: Optional[float] = None, page_count: Optional[int] = None) -> None:
        if status is RunStatus.SUCCESS:
            self.success += 1
        elif status is RunStatus.SKIPPED:
            self.skipped += 1
        elif status is RunStatus.SKIPPED_LARGE:
            self.skipped_large += 1
            self.large_pdfs.append(
                {
                    "company": job.company,
                    "year": job.year,
                    "pdf": str(job.pdf_path),
                    "size_mb": round(size_mb, 1) if size_mb is not None else None,
                    "page_count": page_count,
                    "output_dir": str(job.output_dir),
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
            )
        else:
            self.failed += 1
            self.errors.append(
                {
                    "company": job.company,
                    "year": job.year,
                    "pdf": str(job.pdf_path),
                    "output_dir": str(job.output_dir),
                    "error": error_message or "Erreur inconnue",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
            )


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

def setup_logging(error_log_path: Path) -> None:
    """Configure un logger console + un fichier errors.log dédié aux erreurs."""
    error_log_path.parent.mkdir(parents=True, exist_ok=True)

    log.setLevel(logging.INFO)
    log.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S"))
    log.addHandler(console_handler)

    file_handler = logging.FileHandler(error_log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(file_handler)


# --------------------------------------------------------------------------- #
# Détection robuste d'un traitement déjà terminé
# --------------------------------------------------------------------------- #
#
# mineru_extract_tables.py ne produit que deux artefacts :
#   <output_dir>/<pdf_stem>_tables_analysis.json
#   <output_dir>/selected_tables/{identification,bilan_actif,bilan_passif,cpc}.png
#
# On retient uniquement selected_tables/*.png comme critère de complétion :
# c'est le résultat concret attendu par l'utilisateur, et le seul artefact
# garanti par le script (le nombre de PNG peut varier si une catégorie
# n'est pas trouvée, donc on se contente de vérifier qu'il y en a au moins
# un, signe qu'une exécution complète a eu lieu jusqu'à l'étape F).

def _has_selected_tables(output_dir: Path) -> bool:
    tables_dir = output_dir / SELECTED_TABLES_DIRNAME
    return tables_dir.is_dir() and any(tables_dir.glob("*.png"))


COMPLETION_CHECKS = (_has_selected_tables,)


def is_processing_complete(output_dir: Path) -> bool:
    """Vérifie que le dossier selected_tables/ existe et contient des PNG.

    Volontairement indépendant de toute date de modification (mtime), qui
    n'est pas fiable (copies, horloge système, etc.).
    """
    if not output_dir.exists():
        return False
    return all(check(output_dir) for check in COMPLETION_CHECKS)


# --------------------------------------------------------------------------- #
# Registre completed.json (persistance de la progression)
# --------------------------------------------------------------------------- #

class CompletedRegistry:
    """Registre persistant des PDF traités avec succès.

    Sert de "cache" rapide pour la reprise, mais n'est jamais utilisé seul :
    on revérifie systématiquement les fichiers de sortie sur disque
    (voir is_processing_complete) avant de considérer un PDF comme SKIPPED,
    afin de rester robuste si les fichiers ont été supprimés entre-temps.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning(f"Registre {self.path} illisible ({exc}), il sera recréé.")
            return {}

    def contains(self, key: str) -> bool:
        return key in self._data

    def mark_completed(self, job: PdfJob) -> None:
        self._data[job.key] = {
            "pdf": str(job.pdf_path),
            "output_dir": str(job.output_dir),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def _save(self) -> None:
        """Écriture atomique (fichier temporaire + rename) pour éviter la
        corruption du registre en cas de crash pendant l'écriture."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp"
        ) as tmp_file:
            json.dump(self._data, tmp_file, ensure_ascii=False, indent=2)
            tmp_path = Path(tmp_file.name)
        tmp_path.replace(self.path)


# --------------------------------------------------------------------------- #
# Exécution de mineru_extract_tables.py pour un job donné
# --------------------------------------------------------------------------- #

def run_mineru_pipe(job: PdfJob, backend: str, lang: Optional[str], serie_preference: str) -> tuple[bool, Optional[str]]:
    """Lance scripts/mineru_extract_tables.py pour un PDF. Ne modifie jamais ce script.

    Retourne (succès, message_erreur_ou_None).
    """
    cmd = [
        sys.executable,
        MINERU_SCRIPT_PATH,
        "--pdf", str(job.pdf_path),
        "--output-dir", str(job.output_dir),
        "--backend", backend,
        "--serie-preference", serie_preference,
    ]
    if lang:
        cmd += ["--lang", lang]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if result.stdout.strip():
            log.debug(result.stdout)
        return True, None
    except subprocess.CalledProcessError as exc:
        error_message = exc.stderr.strip() if exc.stderr else str(exc)
        return False, error_message
    except Exception as exc:  # sécurité : ne jamais interrompre le batch entier
        return False, str(exc)


def get_pdf_size_mb(pdf_path: Path) -> float:
    """Taille du PDF en Mo (utilisée comme proxy simple de "volumineux" :
    pas de dépendance externe, pas besoin d'ouvrir/parser le PDF)."""
    return pdf_path.stat().st_size / (1024 * 1024)


def get_pdf_page_count(pdf_path: Path) -> Optional[int]:
    """Nombre de pages du PDF via pypdf. Retourne None en cas d'échec
    (PDF corrompu, dépendances manquantes, etc.) — dans ce cas on ne
    bloque pas le traitement sur le critère pages."""
    if PdfReader is None:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception as exc:
        log.warning(f"Impossible de lire le nombre de pages de {pdf_path.name} : {exc}")
        return None


def process_job(job: PdfJob, registry: CompletedRegistry, backend: str, lang: Optional[str],
                 serie_preference: str, force: bool,
                 max_pdf_size_mb: Optional[float] = None,
                 max_pages: Optional[int] = None) -> tuple[RunStatus, Optional[str], Optional[float], Optional[int]]:
    """Traite un job unique et renvoie son état final (+ message d'erreur éventuel,
    taille Mo et nombre de pages pour le reporting)."""

    already_done = not force and registry.contains(job.key) and is_processing_complete(job.output_dir)
    if already_done:
        return RunStatus.SKIPPED, None, None, None

    # Filet de sécurité : même sans entrée dans le registre, si les fichiers de
    # sortie sont déjà complets (ex: registre perdu), on ne retraite pas.
    if not force and is_processing_complete(job.output_dir):
        registry.mark_completed(job)
        return RunStatus.SKIPPED, None, None, None

    size_mb = get_pdf_size_mb(job.pdf_path)
    page_count = get_pdf_page_count(job.pdf_path)

    # Seuil de pages : 20 pages par défaut = volumineux.
    # Les PDF trop longs ne sont ni SUCCESS ni FAILED : ils sont mis de côté
    # (large_pdfs.json) pour un traitement dédié plus tard, sans jamais être
    # marqués "complétés" dans le registre.
    if max_pages is not None and page_count is not None and page_count > max_pages:
        return (
            RunStatus.SKIPPED_LARGE,
            f"PDF de {page_count} pages > seuil {max_pages} pages",
            size_mb,
            page_count,
        )

    # Seuil de taille (Mo) optionnel, conservé en complément.
    if max_pdf_size_mb is not None and size_mb > max_pdf_size_mb:
        return (
            RunStatus.SKIPPED_LARGE,
            f"PDF de {size_mb:.1f} Mo > seuil {max_pdf_size_mb:.1f} Mo",
            size_mb,
            page_count,
        )

    job.output_dir.mkdir(parents=True, exist_ok=True)
    success, error_message = run_mineru_pipe(job, backend, lang, serie_preference)

    if success and is_processing_complete(job.output_dir):
        registry.mark_completed(job)
        return RunStatus.SUCCESS, None, size_mb, page_count

    if success and not is_processing_complete(job.output_dir):
        # Le sous-process n'a pas levé d'erreur mais les fichiers attendus
        # sont absents/incomplets : on considère cela comme un échec.
        return RunStatus.FAILED, "Traitement terminé sans erreur mais fichiers de sortie incomplets.", size_mb, page_count

    return RunStatus.FAILED, error_message, size_mb, page_count


# --------------------------------------------------------------------------- #
# Construction de la liste des jobs
# --------------------------------------------------------------------------- #

def discover_jobs(rapports_dir: Path, output_base: Path) -> list[PdfJob]:
    """Parcourt Rapports/<entreprise>/<annee>.pdf et construit la liste des jobs."""
    jobs: list[PdfJob] = []
    for company_dir in sorted(p for p in rapports_dir.iterdir() if p.is_dir()):
        for pdf_path in sorted(company_dir.glob("*.pdf")):
            year = pdf_path.stem
            output_dir = output_base / company_dir.name / year
            jobs.append(PdfJob(company=company_dir.name, year=year, pdf_path=pdf_path, output_dir=output_dir))
    return jobs


def filter_for_retry(jobs: list[PdfJob], failed_registry_path: Path) -> list[PdfJob]:
    """En mode --retry-failed, ne garde que les PDF listés comme échoués
    lors du run précédent (batch_report.json / failed_pdfs.json)."""
    if not failed_registry_path.exists():
        log.warning(f"Aucun fichier {failed_registry_path.name} trouvé : --retry-failed n'a rien à relancer.")
        return []

    try:
        failed_entries = json.loads(failed_registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error(f"Impossible de lire {failed_registry_path} : {exc}")
        return []

    failed_pdfs = {entry["pdf"] for entry in failed_entries}
    return [job for job in jobs if str(job.pdf_path) in failed_pdfs]


# --------------------------------------------------------------------------- #
# Rapports de fin de batch
# --------------------------------------------------------------------------- #

def save_batch_report(output_base: Path, stats: BatchStats, start_time: datetime, end_time: datetime) -> None:
    report = {
        "start_time": start_time.isoformat(timespec="seconds"),
        "end_time": end_time.isoformat(timespec="seconds"),
        "duration_seconds": round((end_time - start_time).total_seconds(), 1),
        "total_pdfs": stats.total,
        "success": stats.success,
        "skipped": stats.skipped,
        "failed": stats.failed,
        "skipped_large": stats.skipped_large,
        "errors": stats.errors,
        "large_pdfs": stats.large_pdfs,
    }
    (output_base / BATCH_REPORT_NAME).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_base / FAILED_REGISTRY_NAME).write_text(
        json.dumps(stats.errors, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_base / LARGE_REGISTRY_NAME).write_text(
        json.dumps(stats.large_pdfs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def print_summary(stats: BatchStats, elapsed_seconds: float, output_base: Path, error_log_path: Path) -> None:
    minutes, seconds = divmod(int(elapsed_seconds), 60)
    avg_per_pdf = elapsed_seconds / stats.total if stats.total else 0.0

    log.info(f"\n{'=' * 100}")
    log.info("RÉSUMÉ FINAL")
    log.info(f"{'=' * 100}")
    log.info(f"Total PDF            : {stats.total}")
    log.info(f"Traités avec succès  : {stats.success}")
    log.info(f"Sautés (déjà faits)  : {stats.skipped}")
    log.info(f"Ignorés (volumineux) : {stats.skipped_large}")
    log.info(f"Échecs               : {stats.failed}")
    log.info(f"Temps total          : {minutes} min {seconds} sec")
    log.info(f"Temps moyen / PDF    : {avg_per_pdf:.1f} sec")
    log.info(f"Sortie principale    : {output_base.resolve()}")
    log.info(f"Rapport batch        : {(output_base / BATCH_REPORT_NAME).resolve()}")
    if stats.failed:
        log.warning(f"Erreurs dans : {error_log_path.resolve()}")
        log.warning(f"PDF en échec listés dans : {(output_base / FAILED_REGISTRY_NAME).resolve()}")
    if stats.skipped_large:
        log.warning(f"PDF volumineux (non traités) listés dans : {(output_base / LARGE_REGISTRY_NAME).resolve()}")
    log.info(f"{'=' * 100}")


# --------------------------------------------------------------------------- #
# Programme principal
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lanceur batch avec reprise automatique")
    parser.add_argument("--rapports-dir", type=Path, default=DEFAULT_RAPPORTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--backend", default="pipeline")
    parser.add_argument("--lang", default=None)
    parser.add_argument("--serie-preference", choices=["social", "consolide"], default="social")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Ne relance que les PDF listés en échec lors du run précédent (failed_pdfs.json).",
    )
    parser.add_argument(
        "--max-pdf-size-mb",
        type=float,
        default=None,
        help="Taille maximale (en Mo) d'un PDF pour être traité dans ce run. "
             "Les PDF plus lourds sont ignorés (SKIPPED_LARGE) et listés dans "
             "large_pdfs.json pour un traitement séparé ultérieur. "
             "Par défaut : aucune limite.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Nombre maximal de pages d'un PDF pour être traité dans ce run "
             f"(défaut : {DEFAULT_MAX_PAGES}). Les PDF plus longs sont ignorés "
             f"(SKIPPED_LARGE) et listés dans large_pdfs.json. "
             f"Mettre 0 pour désactiver la limite de pages.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    rapports_dir: Path = args.rapports_dir
    output_base: Path = args.output_dir
    output_base.mkdir(parents=True, exist_ok=True)

    error_log_path = output_base / ERROR_LOG_NAME
    setup_logging(error_log_path)

    if not rapports_dir.exists():
        log.error(f"Dossier Rapports non trouvé : {rapports_dir}")
        return 1

    # 0 = pas de limite de pages
    max_pages: Optional[int] = args.max_pages if args.max_pages > 0 else None

    registry = CompletedRegistry(output_base / COMPLETED_REGISTRY_NAME)
    jobs = discover_jobs(rapports_dir, output_base)

    if args.retry_failed:
        jobs = filter_for_retry(jobs, output_base / FAILED_REGISTRY_NAME)
        if not jobs:
            log.info("Aucun PDF en échec à relancer.")
            return 0

    if max_pages is not None:
        log.info(f"Limite de pages active : {max_pages} pages (au-delà → SKIPPED_LARGE)")
    if args.max_pdf_size_mb is not None:
        log.info(f"Limite de taille active : {args.max_pdf_size_mb:.1f} Mo (au-delà → SKIPPED_LARGE)")

    stats = BatchStats(total=len(jobs))
    start_time = datetime.now()
    start_perf = time.time()

    current_company: Optional[str] = None
    global_bar = tqdm(total=len(jobs), desc="Progression globale", unit="pdf", position=0)

    for job in jobs:
        if job.company != current_company:
            current_company = job.company
            log.info(f"\n{'=' * 100}")
            log.info(f"ENTREPRISE : {current_company}")
            log.info(f"{'=' * 100}\n")

        status, error_message, size_mb, page_count = process_job(
            job,
            registry,
            backend=args.backend,
            lang=args.lang,
            serie_preference=args.serie_preference,
            force=args.retry_failed,
            max_pdf_size_mb=args.max_pdf_size_mb,
            max_pages=max_pages,
        )
        stats.record(job, status, error_message, size_mb=size_mb, page_count=page_count)

        if status is RunStatus.FAILED:
            log.error(f"[FAILED] {job.company}/{job.pdf_path.name} : {error_message}")
        elif status is RunStatus.SKIPPED_LARGE:
            log.warning(f"[SKIPPED_LARGE] {job.company}/{job.pdf_path.name} : {error_message}")
        else:
            log.info(f"[{status.value}] {job.company}/{job.pdf_path.name}")

        elapsed = time.time() - start_perf
        done = stats.success + stats.skipped + stats.failed + stats.skipped_large
        avg = elapsed / done if done else 0.0
        remaining = avg * (stats.total - done)
        global_bar.set_postfix_str(f"avg={avg:.1f}s ETA={remaining / 60:.1f}min")
        global_bar.update(1)

    global_bar.close()

    end_time = datetime.now()
    save_batch_report(output_base, stats, start_time, end_time)
    print_summary(stats, time.time() - start_perf, output_base, error_log_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
