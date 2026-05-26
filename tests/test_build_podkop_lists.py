import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_podkop_lists


class BuildPodkopListsTests(unittest.TestCase):
    def test_extract_domains_from_text_supports_comments_and_common_formats(self) -> None:
        text = """
        // comment
        example.com
        DOMAIN-SUFFIX,YouTube.com
        *.sub.example.org # trailing comment
        invalid_domain
        1.1.1.1
        """

        domains = build_podkop_lists.extract_values_from_text(text, "inline", "domain")

        self.assertEqual(domains, {"example.com", "youtube.com", "sub.example.org"})

    def test_extract_domains_from_text_skips_plain_ipv4_addresses(self) -> None:
        text = """
        158.85.224.171
        8.8.8.8
        openai.com
        """

        domains = build_podkop_lists.extract_values_from_text(text, "inline", "domain")

        self.assertEqual(domains, {"openai.com"})

    def test_extract_domains_from_text_supports_domain_list_community_lines(self) -> None:
        text = """
        full:openaicom.imgix.net
        chatgpt.com
        tiktok.com @!cn
        regexp:^chatgpt-async-webps-prod-\\S+-\\d+\\.webpubsub\\.azure\\.com$
        """

        domains = build_podkop_lists.extract_values_from_text(text, "inline", "domain")

        self.assertEqual(domains, {"chatgpt.com", "openaicom.imgix.net", "tiktok.com"})

    def test_extract_domains_from_text_supports_metacubex_yaml_payload(self) -> None:
        text = """
        payload:
          - +.chatgpt.com
          - +.openai.com
          - chat.com
          - +.turn.livekit.cloud
        """

        domains = build_podkop_lists.extract_values_from_text(text, "inline", "domain")

        self.assertEqual(domains, {"chat.com", "chatgpt.com", "openai.com", "turn.livekit.cloud"})

    def test_extract_domains_from_json_reads_domain_suffix_rules(self) -> None:
        payload = {
            "version": 3,
            "rules": [{"domain_suffix": ["пример.рф", "sub.example.com"]}],
        }

        domains = build_podkop_lists.extract_values_from_json(json.dumps(payload), "inline", "domain")

        self.assertEqual(domains, {"xn--e1afmkfd.xn--p1ai", "sub.example.com"})

    def test_extract_subnets_from_cloudflare_json_api(self) -> None:
        payload = {
            "result": {
                "ipv4_cidrs": ["173.245.48.0/20", "103.21.244.0/22"],
                "ipv6_cidrs": ["2400:cb00::/32"],
            }
        }

        subnets = build_podkop_lists.extract_values_from_json(json.dumps(payload), "inline", "subnet")

        self.assertEqual(subnets, {"103.21.244.0/22", "173.245.48.0/20"})

    def test_extract_subnets_from_aws_ip_ranges_json(self) -> None:
        payload = {
            "syncToken": "1",
            "prefixes": [
                {"ip_prefix": "3.5.140.0/22", "service": "AMAZON", "region": "eu-central-1"},
                {"ip_prefix": "13.32.0.0/15", "service": "CLOUDFRONT", "region": "GLOBAL"},
                {"ipv6_prefix": "2600:9000::/28", "service": "CLOUDFRONT", "region": "GLOBAL"},
            ],
        }

        subnets = build_podkop_lists.extract_values_from_json(json.dumps(payload), "inline", "subnet")

        self.assertEqual(subnets, {"3.5.140.0/22", "13.32.0.0/15"})

    def test_extract_subnets_from_ripestat_announced_prefixes_json(self) -> None:
        payload = {
            "status": "ok",
            "data": {
                "prefixes": [
                    {"prefix": "159.69.0.0/16"},
                    {"prefix": "88.99.0.0/16"},
                    {"prefix": "2a01:4f8::/32"},
                ]
            },
        }

        subnets = build_podkop_lists.extract_values_from_json(json.dumps(payload), "inline", "subnet")

        self.assertEqual(subnets, {"159.69.0.0/16", "88.99.0.0/16"})

    def test_extract_domains_from_text_allows_comment_only_file(self) -> None:
        domains = build_podkop_lists.extract_values_from_text("// only comments\n# and more\n", "inline", "domain")
        self.assertEqual(domains, set())

    def test_extract_subnets_from_mixed_text_filters_only_ip_values(self) -> None:
        text = """
        graph.org
        5.28.192.0/21
        144.31.14.104
        invalid.cidr/999
        2001:db8::/32
        """

        subnets = build_podkop_lists.extract_values_from_text(text, "inline", "subnet")

        self.assertEqual(subnets, {"5.28.192.0/21", "144.31.14.104"})

    def test_normalize_subnet_skips_ipv6_values(self) -> None:
        self.assertIsNone(build_podkop_lists.normalize_subnet("2001:db8::/32"))
        self.assertIsNone(build_podkop_lists.normalize_subnet("2606:4700::6810:85e5"))
        self.assertEqual(build_podkop_lists.normalize_subnet("1.1.1.1"), "1.1.1.1")

    def test_domain_matches_roots_covers_subdomains(self) -> None:
        roots = {"chatgpt.com", "openai.com"}

        self.assertTrue(build_podkop_lists.domain_matches_roots("chatgpt.com", roots))
        self.assertTrue(build_podkop_lists.domain_matches_roots("status.chatgpt.com", roots))
        self.assertTrue(build_podkop_lists.domain_matches_roots("codex.openai.com", roots))
        self.assertFalse(build_podkop_lists.domain_matches_roots("example.com", roots))

    def test_build_output_merges_remote_and_local_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            local_source = project_root / "config" / "manual.txt"
            local_source.parent.mkdir(parents=True, exist_ok=True)
            local_source.write_text("manual.example.com\n", encoding="utf-8")

            config = build_podkop_lists.OutputConfig(
                name="sample",
                kind="domain",
                remote_sources=("https://example.test/list.lst",),
                local_sources=(local_source,),
            )

            with patch.object(
                build_podkop_lists,
                "fetch_remote_text",
                return_value="remote.example.com\nmanual.example.com\n",
            ):
                domains = build_podkop_lists.build_output(config, timeout=1)

        self.assertEqual(domains, ["manual.example.com", "remote.example.com"])

    def test_build_output_excludes_values_from_remote_exclude_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            local_source = project_root / "config" / "manual.txt"
            local_source.parent.mkdir(parents=True, exist_ok=True)
            local_source.write_text("", encoding="utf-8")

            config = build_podkop_lists.OutputConfig(
                name="sample",
                kind="domain",
                remote_sources=("https://example.test/include.lst",),
                local_sources=(local_source,),
                exclude_remote_sources=("https://example.test/exclude.lst",),
            )

            def fake_fetch(source: str, *, kind: str, timeout: int) -> set[str]:
                self.assertEqual(kind, "domain")
                mapping = {
                    "https://example.test/include.lst": {"discord.com", "example.com", "youtube.com"},
                    "https://example.test/exclude.lst": {"discord.com", "youtube.com"},
                }
                return mapping[source]

            with patch.object(build_podkop_lists, "fetch_source_values", side_effect=fake_fetch):
                domains = build_podkop_lists.build_output(config, timeout=1)

        self.assertEqual(domains, ["example.com"])

    def test_build_output_supports_remote_source_fallback_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            local_source = project_root / "config" / "manual.txt"
            local_source.parent.mkdir(parents=True, exist_ok=True)
            local_source.write_text("", encoding="utf-8")

            config = build_podkop_lists.OutputConfig(
                name="sample",
                kind="subnet",
                remote_sources=(),
                remote_source_groups=(
                    build_podkop_lists.RemoteSourceGroup(
                        name="cloudflare",
                        sources=("https://broken.test", "https://api.cloudflare.test"),
                    ),
                ),
                local_sources=(local_source,),
            )

            def fake_fetch(source: str, *, kind: str, timeout: int) -> set[str]:
                if source == "https://broken.test":
                    raise build_podkop_lists.BuildError("boom")
                self.assertEqual(kind, "subnet")
                return {"173.245.48.0/20"}

            with patch.object(build_podkop_lists, "fetch_source_values", side_effect=fake_fetch):
                values = build_podkop_lists.build_output(config, timeout=1)

        self.assertEqual(values, ["173.245.48.0/20"])

    def test_fetch_source_group_uses_cached_values_when_sources_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "cache.lst"
            cache_path.write_text("173.245.48.0/20\n", encoding="utf-8")

            source_group = build_podkop_lists.RemoteSourceGroup(
                name="cloudflare",
                sources=("https://broken-a.test", "https://broken-b.test"),
                cache_path=cache_path,
            )

            with patch.object(build_podkop_lists, "fetch_source_values", side_effect=build_podkop_lists.BuildError("boom")):
                values = build_podkop_lists.fetch_source_group_values(source_group, kind="subnet", timeout=1)

        self.assertEqual(values, {"173.245.48.0/20"})

    def test_fetch_source_group_updates_cache_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "cache.lst"
            source_group = build_podkop_lists.RemoteSourceGroup(
                name="cloudflare",
                sources=("https://api.cloudflare.test",),
                cache_path=cache_path,
            )

            with patch.object(build_podkop_lists, "fetch_source_values", return_value={"173.245.48.0/20"}):
                values = build_podkop_lists.fetch_source_group_values(source_group, kind="subnet", timeout=1)

            cache_body = cache_path.read_text(encoding="utf-8")

        self.assertEqual(values, {"173.245.48.0/20"})
        self.assertEqual(cache_body, "173.245.48.0/20\n")

    def test_resolve_output_domains_adds_ipv4_as_32_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "resolved.lst"
            resolve_config = build_podkop_lists.ResolveConfig(
                output="foreign-domains",
                roots=("openai.com", "telegram.org"),
                roots_files=(),
                cache_path=cache_path,
                limit=10,
                timeout_per_lookup=1,
            )
            built_outputs = {
                "foreign-domains": build_podkop_lists.BuildResult(
                    values=("api.openai.com", "cdn.telegram.org", "example.com"),
                    remote_count=0,
                    local_count=0,
                    resolved_count=0,
                    discovered_count=0,
                    discovery=(),
                )
            }

            def fake_resolve(domain: str, timeout: int) -> set[str]:
                self.assertEqual(timeout, 1)
                mapping = {
                    "api.openai.com": {"1.1.1.1"},
                    "cdn.telegram.org": {"2.2.2.2", "2.2.2.3"},
                }
                return mapping.get(domain, set())

            with patch.object(build_podkop_lists, "resolve_domain_ipv4", side_effect=fake_resolve):
                values = build_podkop_lists.resolve_output_domains(resolve_config, built_outputs)

            cache_body = cache_path.read_text(encoding="utf-8")

        self.assertEqual(values, {"1.1.1.1/32", "2.2.2.2/32", "2.2.2.3/32"})
        self.assertEqual(cache_body, "1.1.1.1/32\n2.2.2.2/32\n2.2.2.3/32\n")

    def test_resolve_output_domains_uses_cache_when_dns_returns_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "resolved.lst"
            cache_path.write_text("3.3.3.3/32\n", encoding="utf-8")
            resolve_config = build_podkop_lists.ResolveConfig(
                output="foreign-domains",
                roots=("openai.com",),
                roots_files=(),
                cache_path=cache_path,
                limit=10,
                timeout_per_lookup=1,
            )
            built_outputs = {
                "foreign-domains": build_podkop_lists.BuildResult(
                    values=("api.openai.com",),
                    remote_count=0,
                    local_count=0,
                    resolved_count=0,
                    discovered_count=0,
                    discovery=(),
                )
            }

            with patch.object(build_podkop_lists, "resolve_domain_ipv4", return_value=set()):
                values = build_podkop_lists.resolve_output_domains(resolve_config, built_outputs)

        self.assertEqual(values, {"3.3.3.3/32"})

    def test_load_resolve_cache_filters_non_global_ipv4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "resolved.lst"
            cache_path.write_text("3.3.3.3/32\n198.18.0.1/32\n10.0.0.1/32\n", encoding="utf-8")
            resolve_config = build_podkop_lists.ResolveConfig(
                output="foreign-domains",
                roots=(),
                roots_files=(),
                cache_path=cache_path,
            )

            values = build_podkop_lists.load_resolve_cache(resolve_config)

        self.assertEqual(values, {"3.3.3.3/32"})

    def test_resolve_output_domains_returns_empty_when_no_public_ip_and_no_cache(self) -> None:
        resolve_config = build_podkop_lists.ResolveConfig(
            output="foreign-domains",
            roots=("openai.com",),
            roots_files=(),
            cache_path=None,
            limit=10,
            timeout_per_lookup=1,
        )
        built_outputs = {
            "foreign-domains": build_podkop_lists.BuildResult(
                values=("api.openai.com",),
                remote_count=0,
                local_count=0,
                resolved_count=0,
                discovered_count=0,
                discovery=(),
            )
        }

        with patch.object(build_podkop_lists, "resolve_domain_ipv4", return_value=set()):
            values = build_podkop_lists.resolve_output_domains(resolve_config, built_outputs)

        self.assertEqual(values, set())

    def test_resolve_domain_ipv4_skips_non_global_addresses(self) -> None:
        fake_infos = [
            (None, None, None, None, ("1.1.1.1", 0)),
            (None, None, None, None, ("198.18.0.1", 0)),
            (None, None, None, None, ("10.0.0.1", 0)),
        ]

        with patch("socket.getaddrinfo", return_value=fake_infos):
            values = build_podkop_lists.resolve_domain_ipv4("example.com", timeout=1)

        self.assertEqual(values, {"1.1.1.1"})

    def test_fetch_crtsh_domains_filters_and_limits_to_root(self) -> None:
        payload = [
            {"name_value": "*.example.com\napi.example.com"},
            {"common_name": "login.example.com"},
            {"name_value": "other.test"},
        ]

        with patch.object(build_podkop_lists, "fetch_remote_text", return_value=json.dumps(payload)):
            domains, warnings = build_podkop_lists.fetch_crtsh_domains("example.com", timeout=1, limit=10)

        self.assertEqual(domains, {"api.example.com", "login.example.com"})
        self.assertEqual(warnings, [])

    def test_fetch_v2fly_domain_values_follows_include_chains(self) -> None:
        parent_url = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/meta"
        facebook_url = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/facebook"
        instagram_url = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/instagram"
        responses = {
            parent_url: "include:facebook\ninclude:instagram\nmeta.ai\nmeta.com\n",
            facebook_url: "facebook.com\nfbcdn.net\n",
            instagram_url: "instagram.com\ncdninstagram.com\n",
        }

        def fake_fetch(source: str, *, timeout: int, retries: int = 3) -> str:
            self.assertIn(source, responses)
            return responses[source]

        with patch.object(build_podkop_lists, "fetch_remote_text", side_effect=fake_fetch):
            domains = build_podkop_lists.fetch_source_values(parent_url, kind="domain", timeout=1)

        self.assertEqual(domains, {"cdninstagram.com", "facebook.com", "fbcdn.net", "instagram.com", "meta.ai", "meta.com"})

    def test_build_output_includes_discovered_domains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            local_source = project_root / "config" / "manual.txt"
            roots_file = project_root / "config" / "roots.txt"
            local_source.parent.mkdir(parents=True, exist_ok=True)
            local_source.write_text("manual.example.com\n", encoding="utf-8")
            roots_file.write_text("example.com\n", encoding="utf-8")

            config = build_podkop_lists.OutputConfig(
                name="sample",
                kind="domain",
                remote_sources=(),
                local_sources=(local_source,),
                discovery=(
                    build_podkop_lists.DiscoveryConfig(
                        provider="crtsh",
                        roots=(),
                        roots_files=(roots_file,),
                        limit_per_root=10,
                    ),
                ),
            )

            with patch.object(build_podkop_lists, "fetch_remote_text", return_value=json.dumps([{"name_value": "api.example.com"}])):
                result = build_podkop_lists.build_output_with_details(config, timeout=1)

        self.assertEqual(list(result.values), ["api.example.com", "manual.example.com"])
        self.assertEqual(result.discovered_count, 1)

    def test_fetch_certspotter_domains_reads_dns_names(self) -> None:
        payload = [
            {"id": 1, "dns_names": ["api.example.com", "*.example.com", "other.test"]},
            {"id": 2, "dns_names": ["login.example.com"]},
        ]

        with patch.object(build_podkop_lists, "fetch_remote_text", side_effect=[json.dumps(payload), "[]"]):
            domains, warnings = build_podkop_lists.fetch_certspotter_domains("example.com", timeout=1, limit=10)

        self.assertEqual(domains, {"api.example.com", "login.example.com"})
        self.assertEqual(warnings, [])

    def test_fetch_urlscan_domains_reads_page_domains(self) -> None:
        payload = {
            "results": [
                {"page": {"domain": "www.example.com"}},
                {"page": {"domain": "api.example.com"}},
                {"page": {"domain": "example.com"}},
                {"page": {"domain": "other.test"}},
            ]
        }

        with patch.object(build_podkop_lists, "fetch_remote_text", return_value=json.dumps(payload)):
            domains, warnings = build_podkop_lists.fetch_urlscan_domains("example.com", timeout=1, limit=150)

        self.assertEqual(domains, {"api.example.com", "www.example.com"})
        self.assertEqual(warnings, [])

    def test_fetch_urlscan_domains_paginates_when_has_more(self) -> None:
        page_one = {
            "results": [
                {"page": {"domain": "www.example.com"}, "sort": ["a", "1"]},
            ],
            "has_more": True,
        }
        page_two = {
            "results": [
                {"page": {"domain": "api.example.com"}, "sort": ["a", "2"]},
            ],
            "has_more": False,
        }

        with patch.object(build_podkop_lists, "fetch_remote_text", side_effect=[json.dumps(page_one), json.dumps(page_two)]):
            domains, warnings = build_podkop_lists.fetch_urlscan_domains("example.com", timeout=1, limit=150)

        self.assertEqual(domains, {"api.example.com", "www.example.com"})
        self.assertEqual(warnings, [])

    def test_fetch_urlscan_domains_stops_after_first_page_when_limit_is_100(self) -> None:
        page_one = {
            "results": [
                {"page": {"domain": "www.example.com"}, "sort": ["a", "1"]},
            ],
            "has_more": True,
        }

        with patch.object(build_podkop_lists, "fetch_remote_text", return_value=json.dumps(page_one)) as mocked_fetch:
            domains, warnings = build_podkop_lists.fetch_urlscan_domains("example.com", timeout=1, limit=100)

        self.assertEqual(domains, {"www.example.com"})
        self.assertEqual(warnings, [])
        self.assertEqual(mocked_fetch.call_count, 1)

    def test_fetch_wayback_domains_reads_hostnames_from_original_urls(self) -> None:
        payload = [
            ["original"],
            ["https://cdn.example.com/asset.js"],
            ["http://api.example.com/v1"],
            ["https://example.com/"],
            ["https://other.test/path"],
        ]

        with patch.object(build_podkop_lists, "fetch_remote_text", return_value=json.dumps(payload)):
            domains, warnings = build_podkop_lists.fetch_wayback_domains("example.com", timeout=1, limit=10)

        self.assertEqual(domains, {"api.example.com", "cdn.example.com"})
        self.assertEqual(warnings, [])

    def test_write_output_files_creates_domain_lst_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            build_podkop_lists.write_output_files(
                output_dir,
                "sample",
                ["a.example.com", "b.example.com"],
                "domain",
            )

            lst_body = (output_dir / "sample.lst").read_text(encoding="utf-8")
            json_body = json.loads((output_dir / "sample.json").read_text(encoding="utf-8"))

        self.assertEqual(lst_body, "a.example.com\nb.example.com\n")
        self.assertEqual(
            json_body,
            {
                "version": 3,
                "rules": [{"domain_suffix": ["a.example.com", "b.example.com"]}],
            },
        )

    def test_write_output_files_creates_subnet_lst_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            build_podkop_lists.write_output_files(
                output_dir,
                "subnets",
                ["1.1.1.1", "5.28.192.0/21"],
                "subnet",
            )

            lst_body = (output_dir / "subnets.lst").read_text(encoding="utf-8")
            json_body = json.loads((output_dir / "subnets.json").read_text(encoding="utf-8"))

        self.assertEqual(lst_body, "1.1.1.1\n5.28.192.0/21\n")
        self.assertEqual(
            json_body,
            {
                "version": 3,
                "rules": [{"ip_cidr": ["1.1.1.1", "5.28.192.0/21"]}],
            },
        )


if __name__ == "__main__":
    unittest.main()
