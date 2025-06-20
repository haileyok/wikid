"""Functionality for creating the knowledge base from downloaded assets and by querying Wikipedia's API."""
import csv
import logging
import os
from pathlib import Path
from typing import List

import numpy
import spacy
import tqdm
import typer
import torch

try:
    from spacy.kb import InMemoryLookupKB as DefaultKB
except ImportError:
    from spacy.kb import KnowledgeBase as DefaultKB
import wiki

device = "cuda" if torch.cuda.is_available() else "cpu"
if device == "cpu":
    print("WARN: Using CPU. Performance will be slow.")
else:
    spacy.require_gpu()


def main(vectors_model: str, language: str, n_process: int):
    """Create the Knowledge Base in spaCy and write it to file.
    language (str): Language.
    vectors_model (str): Name of model with word vectors to use.
    """

    logger = logging.getLogger(__name__)
    nlp = spacy.load(vectors_model, exclude=[])

    logger.info("Constructing knowledge base.")
    kb = DefaultKB(vocab=nlp.vocab,
                   entity_vector_length=nlp.vocab.vectors_length)
    entity_list: List[str] = []
    count_list: List[int] = []
    vector_list: List[numpy.ndarray] = []  # type: ignore
    entities = wiki.load_entities(language=language)
    ent_descriptions = {
        qid: entities[qid].description
        if entities[qid].description
        else (
            entities[qid].article_text[:200]
            if entities[qid].article_text
            else entities[qid].name
        )
        for qid in entities.keys()
    }

    # Infer vectors for entities' descriptions.
    desc_vectors = [
        doc.vector
        for doc in tqdm.tqdm(
            nlp.pipe(
                texts=[ent_descriptions[qid] for qid in entities.keys()], n_process=n_process
            ),
            total=len(entities),
            desc="Inferring entity embeddings",
        )
    ]
    for qid, desc_vector in zip(entities.keys(), desc_vectors):
        entity_list.append(qid)
        count_list.append(entities[qid].count)
        vector_list.append(
            desc_vector if isinstance(
                desc_vector, numpy.ndarray) else desc_vector.get()
        )
    kb.set_entities(
        entity_list=entity_list, vector_list=vector_list, freq_list=count_list
    )

    # Add aliases with normalized priors to KB. This won't be necessary with a custom KB.
    alias_entity_prior_probs = wiki.load_alias_entity_prior_probabilities(
        language=language
    )
    for alias, entity_prior_probs in alias_entity_prior_probs.items():
        kb.add_alias(
            alias=alias,
            entities=[epp[0] for epp in entity_prior_probs],
            probabilities=[epp[1] for epp in entity_prior_probs],
        )
    # Add pseudo aliases for easier lookup with new candidate generators.
    for entity_id in entity_list:
        kb.add_alias(
            alias="_" + entity_id + "_", entities=[entity_id], probabilities=[1]
        )

    # Serialize knowledge base & pipeline.
    output_dir = Path(os.path.abspath(__file__)).parent.parent / "output"
    kb.to_disk(output_dir / language / "kb")
    nlp_dir = output_dir / language / "nlp"
    os.makedirs(nlp_dir, exist_ok=True)
    nlp.to_disk(nlp_dir)
    # # Write descriptions to file.
    with open(
        output_dir / language / "descriptions.csv", "w", encoding="utf-8"
    ) as csvfile:
        csv_writer = csv.writer(csvfile, quoting=csv.QUOTE_MINIMAL)
        for qid, ent_desc in ent_descriptions.items():
            csv_writer.writerow([qid, ent_desc])
    logger.info("Successfully constructed knowledge base.")


if __name__ == "__main__":
    typer.run(main)
