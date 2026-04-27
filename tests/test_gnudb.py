from __future__ import annotations

import unittest
from unittest.mock import patch

from discvault.metadata.gnudb import _cddbp_exchange, parse_cddb_record


class ParseCddbRecordTests(unittest.TestCase):
    def test_canonical_dtitle_and_ttitle_split_on_slash(self) -> None:
        record = (
            "DTITLE=Various / Compilation\n"
            "DYEAR=2001\n"
            "TTITLE0=First Artist / First Track\n"
            "TTITLE1=Second Artist / Second Track\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Various")
        self.assertEqual(meta.album, "Compilation")
        self.assertEqual(meta.year, "2001")
        self.assertEqual(len(meta.tracks), 2)
        self.assertEqual(meta.tracks[0].title, "First Track")
        self.assertEqual(meta.tracks[0].artist, "First Artist")
        self.assertEqual(meta.tracks[1].title, "Second Track")
        self.assertEqual(meta.tracks[1].artist, "Second Artist")

    def test_strips_redundant_artist_prefix_from_album_and_tracks(self) -> None:
        # Real-world shape observed in GnuDB cache for this CCR record.
        record = (
            "DTITLE=Creedence Clearwater Revival /"
            " Creedence Clearwater Revival - Bayou Country\n"
            "DYEAR=1969\n"
            "TTITLE0=Creedence Clearwater Revival - Born On The Bayou\n"
            "TTITLE1=Creedence Clearwater Revival - Bootleg\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Creedence Clearwater Revival")
        self.assertEqual(meta.album, "Bayou Country")
        self.assertEqual(meta.tracks[0].title, "Born On The Bayou")
        self.assertEqual(meta.tracks[0].artist, "Creedence Clearwater Revival")
        self.assertEqual(meta.tracks[1].title, "Bootleg")
        self.assertEqual(meta.tracks[1].artist, "Creedence Clearwater Revival")

    def test_legitimate_hyphen_in_track_title_is_preserved(self) -> None:
        # Track title contains " - " but the prefix does NOT match the album
        # artist, so it must not be stripped.
        record = (
            "DTITLE=Bruce Springsteen / Live 1975-85\n"
            "TTITLE0=Born In The U.S.A. - Live\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Bruce Springsteen")
        self.assertEqual(meta.album, "Live 1975-85")
        self.assertEqual(meta.tracks[0].title, "Born In The U.S.A. - Live")
        self.assertEqual(meta.tracks[0].artist, "")

    def test_strip_is_case_insensitive(self) -> None:
        record = (
            "DTITLE=The Beatles / Abbey Road\n"
            "TTITLE0=THE BEATLES - Come Together\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.tracks[0].title, "Come Together")
        self.assertEqual(meta.tracks[0].artist, "The Beatles")

    def test_falls_back_to_dartist_when_no_slash_in_dtitle(self) -> None:
        record = (
            "DTITLE=Untitled Album\n"
            "DARTIST=Some Artist\n"
            "TTITLE0=Track One\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Some Artist")
        self.assertEqual(meta.album, "Untitled Album")
        self.assertEqual(meta.tracks[0].title, "Track One")
        self.assertEqual(meta.tracks[0].artist, "")


class CddbpExchangeTests(unittest.TestCase):
    def _fake_socket(self, chunks: list[bytes]) -> "object":
        chunks_iter = iter(chunks)
        recv_calls = []
        sent: list[bytes] = []

        class FakeSocket:
            def settimeout(self, _t: float) -> None:
                pass

            def recv(self, _n: int) -> bytes:
                recv_calls.append(True)
                try:
                    return next(chunks_iter)
                except StopIteration:
                    raise AssertionError(
                        "recv called past the end of the scripted server output"
                    )

            def sendall(self, payload: bytes) -> None:
                sent.append(payload)

            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, *_a: object) -> None:
                pass

        sock = FakeSocket()
        sock.recv_calls = recv_calls  # type: ignore[attr-defined]
        sock.sent = sent  # type: ignore[attr-defined]
        return sock

    def test_sends_each_command_separately_and_reads_its_response(self) -> None:
        # gnudb.gnudb.org rejects pipelined commands with "500 Command syntax
        # error". Sending one at a time is the fix. Verify each command lands
        # as its own sendall and the matching response is read inline.
        sock = self._fake_socket([
            b"200 banner ready\r\n",
            b"200 hello\r\n",
            b"201 OK CDDB protocol level: 6\r\n",
            b"202 no match\r\n",
            b"230 closing connection\r\n",
        ])

        with patch("discvault.metadata.gnudb.socket.create_connection", return_value=sock):
            response = _cddbp_exchange(
                "gnudb.example",
                8880,
                ["cddb hello user host disc 1.0", "proto 6", "cddb query 12345678 1 0 1", "quit"],
                timeout=8,
            )

        self.assertIn("200 hello", response)
        self.assertIn("201 OK", response)
        self.assertIn("202 no match", response)
        self.assertIn("230 closing connection", response)
        self.assertEqual(len(sock.sent), 4)  # type: ignore[attr-defined]
        self.assertEqual(sock.sent[0], b"cddb hello user host disc 1.0\r\n")  # type: ignore[attr-defined]
        self.assertEqual(sock.sent[1], b"proto 6\r\n")  # type: ignore[attr-defined]
        self.assertEqual(sock.sent[2], b"cddb query 12345678 1 0 1\r\n")  # type: ignore[attr-defined]
        self.assertEqual(sock.sent[3], b"quit\r\n")  # type: ignore[attr-defined]
        self.assertEqual(len(sock.recv_calls), 5)  # type: ignore[attr-defined]

    def test_multi_line_response_reads_until_dot_terminator(self) -> None:
        # A "cddb read" response is multi-line (210) and ends with "\r\n.\r\n".
        # The reader must wait for the terminator before treating the response
        # as complete; otherwise the next command would interleave.
        sock = self._fake_socket([
            b"200 banner ready\r\n",
            b"200 hello\r\n",
            b"201 OK CDDB protocol level: 6\r\n",
            b"210 OK CDDB entry follows\r\n",
            b"DISCID=12345678\r\nDTITLE=Artist / Album\r\n",
            b"TTITLE0=One\r\n.\r\n",
            b"230 closing connection\r\n",
        ])

        with patch("discvault.metadata.gnudb.socket.create_connection", return_value=sock):
            response = _cddbp_exchange(
                "gnudb.example",
                8880,
                ["cddb hello u h d 1.0", "proto 6", "cddb read rock 12345678", "quit"],
                timeout=8,
            )

        self.assertIn("210 OK CDDB entry follows", response)
        self.assertIn("DTITLE=Artist / Album", response)
        self.assertIn("TTITLE0=One", response)
        self.assertIn("\n.\n", response)
        self.assertIn("230 closing connection", response)
        self.assertEqual(len(sock.sent), 4)  # type: ignore[attr-defined]

    def test_response_chunks_split_across_recvs_are_assembled(self) -> None:
        # TCP can split lines mid-way; the per-command reader must keep
        # accumulating until it has at least one full line.
        sock = self._fake_socket([
            b"200 banner ready\r\n",
            b"200 he",
            b"llo\r\n",
            b"201 OK CDDB protocol level: 6\r\n",
            b"230 bye\r\n",
        ])

        with patch("discvault.metadata.gnudb.socket.create_connection", return_value=sock):
            response = _cddbp_exchange(
                "gnudb.example",
                8880,
                ["cddb hello u h d 1.0", "proto 6", "quit"],
                timeout=8,
            )

        self.assertIn("200 hello", response)
        self.assertIn("201 OK", response)
        self.assertIn("230 bye", response)
        self.assertEqual(len(sock.sent), 3)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
