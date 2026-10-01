from weir_eval.dataset import EvalQuery


def q(id, cluster, group="distinct", split=None, facts=("4 pm",), ns="weir-general/en/public", docs=("pub-a",)):
    return EvalQuery(id=id, namespace=ns, query=f"question {id}", group=group, cluster_id=cluster,
                     difficulty="easy", required_facts=list(facts), source_docs=list(docs), split=split)
