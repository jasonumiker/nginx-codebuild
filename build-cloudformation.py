# Template to create a CodeBuild Project to build nginx
# By Jason Umiker (jason.umiker@gmail.com)

from troposphere import Output, Join, Ref, Template
from troposphere import AWS_ACCOUNT_ID, AWS_REGION
from troposphere import ecr, s3, iam, codebuild

t = Template()

# Create the nginx Repository
Repository = t.add_resource(
    ecr.Repository(
        "Repository",
        RepositoryName="nginx"
    )
)

# Create the S3 Bucket for Output
NginxBuildOutputBucket = t.add_resource(
    s3.Bucket(
        "NginxBuildOutputBucket"
    )
)

# CodeBuild Service Role
CodeBuildServiceRole = t.add_resource(iam.Role(
    "CodeBuildServiceRole",
    AssumeRolePolicyDocument={
        "Statement": [
            {
                'Effect': 'Allow',
                'Principal': {'Service': 'codebuild.amazonaws.com'},
                "Action": "sts:AssumeRole"
            }
        ]
    }
))

# CodeBuild Service Policy
CodeBuildServiceRolePolicy = t.add_resource(iam.PolicyType(
    "CodeBuildServiceRolePolicy",
    PolicyName="CodeBuildServiceRolePolicy",
    PolicyDocument={"Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "CloudWatchLogsPolicy",
                            "Effect": "Allow",
                            "Action": [
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents"
                            ],
                            "Resource": [
                                "*"
                            ]
                        },
                        {
                            "Sid": "CodeCommitPolicy",
                            "Effect": "Allow",
                            "Action": [
                                "codecommit:GitPull"
                            ],
                            "Resource": [
                                "*"
                            ]
                        },
                        {
                            "Sid": "S3GetObjectPolicy",
                            "Effect": "Allow",
                            "Action": [
                                "s3:GetObject",
                                "s3:GetObjectVersion"
                            ],
                            "Resource": [
                                "*"
                            ]
                        },
                        {
                            "Sid": "S3PutObjectPolicy",
                            "Effect": "Allow",
                            "Action": [
                                "s3:PutObject"
                            ],
                            "Resource": [
                                "*"
                            ]
                        },
                        {'Action': ['ecr:GetAuthorizationToken'],
                         'Resource': ['*'],
                         'Effect': 'Allow'},
                        {'Action': ['ecr:*'],
                         'Resource': [
                             Join("", ["arn:aws:ecr:",
                                       Ref(AWS_REGION),
                                       ":", Ref(AWS_ACCOUNT_ID),
                                       ":repository/",
                                       Ref(Repository)]
                                  ),
                         ],
                         'Effect': 'Allow'},
                    ]},
    Roles=[Ref(CodeBuildServiceRole)],
))

# Create CodeBuild Projects
# Image Build
BuildArtifacts = codebuild.Artifacts(
    Type='S3',
    Name='artifacts',
    Location=Ref(NginxBuildOutputBucket)
)

BuildEnvironment = codebuild.Environment(
    ComputeType="BUILD_GENERAL1_SMALL",
    Image="aws/codebuild/amazonlinux2-x86_64-standard:1.0",
    Type="LINUX_CONTAINER",
    EnvironmentVariables=[{'Name': 'AWS_ACCOUNT_ID', 'Value': Ref(AWS_ACCOUNT_ID)},
                          {'Name': 'IMAGE_REPO_NAME', 'Value': Ref(Repository)},
                          {'Name': 'IMAGE_TAG', 'Value': 'latest'}],
    PrivilegedMode=True
)

BuildSource = codebuild.Source(
    Location="https://github.com/jasonumiker/nginx-codebuild",
    Type="GITHUB"
)

BuildProject = codebuild.Project(
    "BuildProject",
    Artifacts=BuildArtifacts,
    Environment=BuildEnvironment,
    Name="nginx-build",
    ServiceRole=Ref(CodeBuildServiceRole),
    Source=BuildSource,
    DependsOn=CodeBuildServiceRolePolicy
)
t.add_resource(BuildProject)

# Create the CodePipeline IAM Role
CodePipelineServiceRole = t.add_resource(iam.Role(
    "CodePipelineServiceRole",
    AssumeRolePolicyDocument={
        'Statement': [{
            'Effect': 'Allow',
            'Principal': {'Service': ['codepipeline.amazonaws.com']},
            'Action': ["sts:AssumeRole"]
        }]},
))

# Create the Inline policy for the CodePipline Role
CodePipelineServicePolicy = t.add_resource(iam.PolicyType(
    "CodePipelineServicePolicy",
    PolicyName="CodePipelineServicePolicy",
    PolicyDocument={
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ecs:DescribeTaskDefinition",
                    "ecs:RegisterTaskDefinition",
                    "ecs:DescribeServices",
                    "ecs:UpdateService",
                    "ecs:DescribeTasks",
                    "ecs:ListTasks"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "codebuild:StartBuild",
                    "codebuild:BatchGetBuilds"
                ],
                "Resource": [
                    Join("", ["arn:aws:codebuild:", Ref('AWS::Region'), ":", Ref('AWS::AccountId'), ":project/", Ref(BuildProject)])
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucket",
                    "s3:PutObject",
                    "s3:GetObject"
                ],
                "Resource": ["*"]
            }
        ]
    },
    Roles = [Ref(CodePipelineServiceRole)],
))

# Output clair repository URL
t.add_output(Output(
    "RepositoryURL",
    Description="The docker repository URL",
    Value=Join("", [
        Ref(AWS_ACCOUNT_ID),
        ".dkr.ecr.",
        Ref(AWS_REGION),
        ".amazonaws.com/",
        Ref(Repository)
    ]),
))

print(t.to_json())
