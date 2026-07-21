"""
Shim for middleware.observability used by metrics blueprint.
"""


class _Collector:
    def export_prometheus(self):
        return "# metrics unavailable\n"

    def get_metrics(self):
        return {}


def get_metrics_collector():
    return _Collector()
