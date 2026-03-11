#!/usr/bin/env bash
# This test is excluded as it was too inconsistent. On the same branch it would sometimes succeed and sometimes not.
export DOTNET_TEST_FILTER="FullyQualifiedName!=LiteDB.Tests.Issues.Issue2534_Tests.Test"